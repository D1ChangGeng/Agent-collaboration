"""Current wheel runs its maintainer after a separate installed client exits.

The PostgreSQL authority and NodeJournal are real, in disposable namespaces.
Native is an explicit fixture callback. This is installed-package E2 evidence,
not a production service upgrade, actual Native turn, or public deployment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture

CHILD = r'''
import asyncio,json,os,sys,time
from pathlib import Path
import runtime
from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery_models import InvocationObservation
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.models import AuthenticatedContext
from runtime.node import NodeJournal
from runtime.project_schema_state import verify_project_schema
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService

installed=Path(os.environ['ACS_INSTALLED_ROOT']).resolve()
assert Path(runtime.__file__).resolve().is_relative_to(installed)
config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
directory=Path(sys.argv[1]).parent
context=AuthenticatedContext(**config['context'])
authority=DomainAuthority(os.environ['ACS_INSTALLED_DSN'],context=context)
verify_project_schema(authority)
shared=SharedService(authority,LocalCredentialAuthenticator(context))
credential=os.environ['ACS_INSTALLED_CREDENTIAL']
if sys.argv[2]=='client':
    service=ProjectService(shared,config['catalog'],profile='root_manager')
    state,data,_=service.execute('send_message',{'project_id':'project-alpha','to':'collaborator:project-alpha:slot-b',
        'content':'Installed client closed; independent maintenance must advance this message',
        'client_request_id':'t090-installed-client','activation':'invoke'},credential)
    (directory/'receipt.json').write_text(json.dumps({'state':state,'message_id':data['message_id'],
        'operation_id':data['operation_id'],'module':str(runtime.__file__)}),encoding='utf-8')
else:
    class FixtureDriver:
        evidence_class='fixture_callback'
        def prepare(self,invocation): return invocation
        def invoke(self,invocation):
            with (directory/'fixture-calls.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'operation_id':invocation.operation_id})+'\n')
            return InvocationObservation(invocation_id=invocation.invocation_id,dispatch_id=invocation.dispatch_id,
                runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
                native_dispatch_ref='installed-fixture-dispatch',native_ack_ref='installed-fixture-ack')
    endpoints={}
    for reference,item in config['endpoints'].items():
        d=item['descriptor']
        journal=NodeJournal(item['journal'],machine_id=d['machine_id'],node_id=d['node_id'],boot_incarnation=d['boot_incarnation'])
        endpoints[reference]=LocalNodeEndpoint(journal,d['scope_id'],d['agent_slot_id'],FixtureDriver())
    authority._delivery_endpoints=endpoints
    (directory/'started.json').write_text(json.dumps({'module':str(runtime.__file__)}),encoding='utf-8')
    async def maintain():
        from runtime.communication_dispatch import maintain_communication_deliveries
        deadline=time.monotonic()+40
        while not (directory/'client-exited').exists():
            if (directory/'stop').exists() or time.monotonic()>deadline: return
            await asyncio.sleep(0.02)
        task=asyncio.create_task(maintain_communication_deliveries(shared))
        try:
            while not (directory/'stop').exists() and time.monotonic()<deadline:
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(maintain())
'''


def test_t090_installed_wheel_maintains_committed_message_after_its_client_process_exits(comm, tmp_path, record_property):
    configured = os.environ.get("ACS_REVISION_TEST_INSTALL")
    if not configured:
        pytest.skip("explicit isolated candidate wheel installation required")
    installed = Path(configured).resolve()
    assert (installed / "runtime/communication_dispatch.py").is_file()
    configuration = {"context": asdict(comm.authority.context), "catalog": CATALOG, "endpoints": {
        reference: {"journal": endpoint.journal._path, "descriptor": endpoint.descriptor()}
        for reference, endpoint in comm.dispatcher.service.endpoints.items()}}
    config = tmp_path / "installed-test.json"
    config.write_text(json.dumps(configuration), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(installed), ACS_INSTALLED_ROOT=str(installed),
               ACS_INSTALLED_DSN=comm.dsn, ACS_INSTALLED_CREDENTIAL=comm.clients["a"].credential_provider())
    args = [sys.executable, "-c", CHILD, str(config)]
    worker = subprocess.Popen([*args, "worker"], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / "started.json").exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.03)
        assert (tmp_path / "started.json").exists(), "installed worker failed to start"
        sender = subprocess.run([*args, "client"], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=20, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert sender.returncode == 0, sender.stderr.decode(errors="replace")
        receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
        assert Path(receipt["module"]).resolve().is_relative_to(installed)
        assert worker.poll() is None and not (tmp_path / "fixture-calls.jsonl").exists()
        (tmp_path / "client-exited").touch()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with comm.authority._connect() as connection:
                state = connection.execute("SELECT state,receipt_high_water FROM delivery_messages WHERE message_id=%s",
                                           (receipt["message_id"],)).fetchone()
            if state == ("delivered", "runtime_acknowledged"):
                break
            time.sleep(0.05)
        assert state == ("delivered", "runtime_acknowledged")
        calls = (tmp_path / "fixture-calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(value)["operation_id"] for value in calls] == [receipt["operation_id"]]
        with comm.authority._connect() as connection:
            assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
        record_property("installed_module", receipt["module"])
        record_property("closed_client_before_dispatch", "true")
        record_property("evidence_class", "E2_installed_wheel_PG_NodeJournal_fixture_Native")
    finally:
        (tmp_path / "stop").touch()
        try:
            worker.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.communicate(timeout=10)
            raise AssertionError("owned installed worker did not stop") from None
