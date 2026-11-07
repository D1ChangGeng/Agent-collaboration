"""Kill real writers at the Core transaction's durable-write boundaries.

Uses the current Core, actual isolated PostgreSQL and a child OS process. No
Native calls occur. Database sequences may advance across rolled-back writes;
message, reply, operation, Outbox and event facts must remain atomic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from threading import Barrier

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_client_events import evented as evented_fixture
from runtime_tests.test_communication_p2_exact_scenarios import second_device

comm = comm_fixture
evented = evented_fixture
ROOT = Path(__file__).resolve().parents[1]
TABLES = ("communication_messages", "communication_replies", "delivery_messages", "delivery_receipts",
          "operations", "outbox", "domain_events", "command_dedup", "collaboration_commands", "communication_event_intents")
CHILD = r'''
import json,os,sys,time
from pathlib import Path
import psycopg
import runtime.domain as domain
from runtime.auth import LocalCredentialAuthenticator
from runtime.models import AuthenticatedContext
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService

checkpoint, marker = sys.argv[1:]
class CheckpointCursor(psycopg.Cursor):
    def execute(self, query, params=None, **kwargs):
        result = super().execute(query, params, **kwargs)
        if isinstance(query,str) and query.startswith(('INSERT INTO '+checkpoint+'(', 'INSERT INTO '+checkpoint+' ')):
            Path(marker).write_text(checkpoint,encoding='utf-8')
            while True: time.sleep(0.05)
        return result
connect = domain.connect
def paused_connect(*args, **kwargs):
    return connect(*args, **kwargs, cursor_factory=CheckpointCursor)
domain.connect = paused_connect
context = AuthenticatedContext(**json.loads(os.environ['ACS_CRASH_CONTEXT']))
authority = domain.DomainAuthority(os.environ['ACS_CRASH_DSN'],context=context)
catalog = json.loads(Path(os.environ['ACS_CRASH_CATALOG']).read_text(encoding='utf-8'))
projects = ProjectService(SharedService(authority,LocalCredentialAuthenticator(context)),catalog,profile='engineer')
args = json.loads(os.environ['ACS_CRASH_ARGS'])
projects.execute('send_message',args,os.environ['ACS_CRASH_CREDENTIAL'])
raise AssertionError('writer unexpectedly acknowledged before the crash checkpoint')
'''


def records(f):
    with f.authority._connect() as connection:
        return {name: connection.execute("SELECT to_jsonb(t) FROM " + name +
            " t ORDER BY to_jsonb(t)::text").fetchall() for name in TABLES}


@pytest.mark.parametrize("checkpoint", [
    "delivery_messages", "communication_messages", "communication_replies", "collaboration_commands",
])
def test_t008_killed_writer_cannot_ack_or_leave_partial_message_reply_outbox_or_event(evented, tmp_path, checkpoint):
    f = evented
    original = send(f, activation="message_only")["data"]
    before = records(f)
    actor = f.clients["b"]
    arguments = {"project_id": "project-alpha", "to": "collaborator:project-alpha:local-slot",
                 "content": "A real reply interrupted before its transaction commits",
                 "activation": "message_only", "reply_to": [original["message_handle"]],
                 "client_request_id": "t008-recover-original-key"}
    environment = dict(os.environ, ACS_CRASH_DSN=f.dsn,
        ACS_CRASH_CONTEXT=json.dumps(asdict(actor.service.context)),
        ACS_CRASH_CREDENTIAL=actor.credential_provider(), ACS_CRASH_ARGS=json.dumps(arguments),
        ACS_CRASH_CATALOG=str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"))
    marker = tmp_path / "write-boundary.txt"
    process = subprocess.Popen([sys.executable, "-c", CHILD, checkpoint, str(marker)], cwd=ROOT,
        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "real writer did not reach the selected SQL boundary"
        assert process.poll() is None, "the writer must still be inside its uncommitted transaction"
        process.terminate()
        process.wait(timeout=10)
        assert records(f) == before
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
    recovered = actor.service.execute("send_message", arguments, actor.credential_provider())[1]
    replayed = actor.service.execute("send_message", arguments, actor.credential_provider())[1]
    assert replayed["message_handle"] == recovered["message_handle"] and replayed["duplicate"]
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='message.delivery'").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_event_intents WHERE kind='reply.linked'").fetchone() == (1,)
    assert not any(driver.calls for driver in f.drivers.values())


def test_t009_same_request_key_across_device_connections_has_one_committed_operation(evented):
    f = evented
    devices = [second_device(f, "a"), second_device(f, "a")]
    arguments = {"to": "collaborator:project-alpha:slot-b", "content": "Identical text has explicit request identity",
                 "activation": "message_only"}
    ready = Barrier(2)

    def submit(number):
        ready.wait(timeout=10)
        return devices[number].send("project-alpha", arguments, client_request_id="t009-shared-key")

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(submit, (0, 1)))
    assert len({value["message"]["message_handle"] for value in accepted}) == 1
    assert len({value["operation_ref"] for value in accepted}) == 1
    assert sorted(value["duplicate"] for value in accepted) == [False, True]
    distinct = [devices[number].send("project-alpha", arguments, client_request_id="t009-distinct-" + str(number))
                for number in (0, 1)]
    assert len({value["message"]["message_handle"] for value in [*accepted, *distinct]}) == 3
    with f.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM outbox WHERE topic='message.delivery'").fetchone() == (3,)
    assert not any(driver.calls for driver in f.drivers.values())
