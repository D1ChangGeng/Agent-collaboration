"""Owner OpenCode factory boundaries; fake native lifecycle is labeled explicitly."""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.receiver_deployment import inspect_factory
from runtime_deployment.receiver_authority import NativeReceiverAuthority, NativeReceiverRejected
from runtime_deployment.receiver_opencode import SCHEMA, OpenCodeReceiverCapacity, validate_settings
from runtime_tests.test_communication import call, send
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture


def settings(tmp_path):
    return {"schema_version":SCHEMA, "binding_id":"opencode-binding", "capacity_attempt_id":"opencode-capacity",
        "executable":str(tmp_path/"opencode"), "cwd":str(tmp_path), "home":str(tmp_path/"selected-home"),
        "driver_journal":str(tmp_path/"driver.sqlite"), "node_journal":str(tmp_path/"node.sqlite"), "runtime_id":"runtime"}


def test_native_defaults_are_inherited_and_invalid_partial_selection_is_rejected(tmp_path):
    supplied=settings(tmp_path)
    resolved=validate_settings(supplied)
    assert all(resolved[key] is None for key in ("agent","provider_id","model_id"))
    assert resolved["config_root"] == str(tmp_path/"selected-home/.config")
    assert not (tmp_path/"selected-home").exists(), "validation itself must not prepare the environment"
    for changed in ({"provider_id":"provider"},{"model_id":"model"},{"executable":"relative"},
                    {"schema_version":"wrong"},{"unknown":"field"}):
        with pytest.raises(NativeReceiverRejected):
            validate_settings({**supplied,**changed})


def test_shared_profile_cannot_silently_take_owner_native_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime_deployment.receiver_opencode.DomainAuthority",
                        lambda *_args,**_kwargs: pytest.fail("must refuse before connecting to Domain"))
    with pytest.raises(NativeReceiverRejected,match="Shared profile"):
        OpenCodeReceiverCapacity(SimpleNamespace(access_mode="shared"),"policy",settings(tmp_path))


def test_opencode_callbacks_are_bound_to_the_measured_deployment_package():
    binding,factory,_origin,_identity=inspect_factory("runtime_deployment.receiver_opencode:callbacks")
    assert callable(factory) and binding.reference=="runtime_deployment.receiver_opencode:callbacks"
    assert len(binding.module_sha256)==len(binding.package_sha256)==64


def test_rejected_lifecycle_close_still_releases_transport_and_owned_supervision():
    calls=[]
    capacity=object.__new__(NativeReceiverAuthority)
    capacity._closed=False
    capacity._lifecycle_operation=lambda _action: object()
    def revoked(_operation):
        calls.append("rejected")
        raise NativeReceiverRejected("revoked")
    capacity.driver=SimpleNamespace(owned=SimpleNamespace(process=SimpleNamespace(poll=lambda:None)),
        terminate=revoked,detach_transport=lambda:calls.append("detach"))
    capacity.supervisor=SimpleNamespace(close=lambda:calls.append("owned_stop"))
    with pytest.raises(NativeReceiverRejected,match="revoked"):
        capacity.close()
    capacity.close()
    assert calls==["rejected","detach","owned_stop"]


def test_opencode_receiver_rechecks_the_committed_sender_not_its_observer(comm):
    import json

    from runtime.delivery_models import PACKET
    from runtime.errors import AuthorizationDenied
    from runtime.models import CommandEnvelope

    submitted=send(comm)["data"]
    capacity=object.__new__(OpenCodeReceiverCapacity)
    capacity.authority=comm.clients["b"].service.service.authority
    capacity.config=SimpleNamespace(access_mode="shared",clock_skew_seconds=0)
    with comm.authority._connect() as connection,connection.cursor() as cursor:
        cursor.execute("SELECT command_json,packet_json FROM delivery_messages WHERE message_id=%s",(submitted["message_id"],))
        command_json,packet_json=cursor.fetchone()
        command=CommandEnvelope.model_validate_json(json.dumps(command_json),strict=True)
        packet=PACKET.validate_json(json.dumps(packet_json),strict=True)
        capacity._authorize_domain_command(command,cursor,"runtime.invoke",packet.target_scope_id,packet)
        cursor.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",(command.grant_ref,))
        with pytest.raises(AuthorizationDenied):
            capacity._authorize_domain_command(command,cursor,"runtime.invoke",packet.target_scope_id,packet)


def enrolled_opencode_config(comm,tmp_path):
    import json

    from nacl.signing import SigningKey

    from runtime.enrollment_models import NodeEnrollment, RuntimeRegistration
    from runtime.receiver_crypto import public_key
    from runtime.receiver_models import EndpointRegistration
    from runtime_tests.test_receiver_domain_delivery import command, proof

    observer=comm.clients["b"].service.service.authority
    with comm.authority._connect() as connection:
        for grant,scope in ((comm.authority.context.grant_ref,"enrollment.manage"),(observer.context.grant_ref,"runtime.register")):
            connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref=%s",(json.dumps([scope]),grant))
    key=SigningKey.generate()
    comm.authority.enroll_node(command(comm.authority,"node.enroll","node","opencode-node"),NodeEnrollment(
        scope_id="local-scope",agent_slot_id="slot-b",observer_grant_ref=observer.context.grant_ref,machine_id="machine",
        boot_incarnation="boot",public_key=public_key(key),expires_at=datetime.now(UTC)+timedelta(minutes=5)))
    request=RuntimeRegistration(node_id="opencode-node",node_binding_revision=1,provider="receiver-tls",
        producer_grant_ref=observer.context.grant_ref,expires_at=datetime.now(UTC)+timedelta(minutes=4))
    registration_command=command(observer,"runtime.register","runtime","runtime")
    observer.register_runtime(registration_command,request,proof(observer,key,"opencode-node",registration_command,
        {"request":request.model_dump(mode="json")}))
    registration=EndpointRegistration(registration_id="opencode",endpoint_id="opencode-endpoint",endpoint_revision=1,
        connection_ref="test-local",tenant_id=comm.authority.tenant_id,authority_id=comm.authority.context.authority_id,
        authority_incarnation=comm.authority.context.authority_incarnation,node_id="opencode-node",node_binding_revision=1,
        runtime_id="runtime",runtime_revision=1,machine_id="machine",boot_incarnation="boot",scope_id="local-scope",
        agent_slot_id="slot-b",tls_certificate_sha256="a"*64,config_sha256="c"*64)
    config=SimpleNamespace(access_mode="owner",binding=SimpleNamespace(registration=registration),journal_generation=1,
                           ledger_path=str(tmp_path/"receiver.sqlite"),clock_skew_seconds=0)
    supplied=settings(tmp_path)
    return config,supplied,observer


def test_factory_binds_real_enrollment_and_inherited_selection_with_a_labeled_native_fixture(comm,tmp_path,monkeypatch):
    from runtime.connection_clock import ClockUncertain
    from runtime.errors import AcceptanceGuardFailed
    from runtime.opencode_driver import OpenCodeNativeDriver
    config,supplied,observer=enrolled_opencode_config(comm,tmp_path)
    Path(supplied["executable"]).write_bytes(b"fixture executable is never launched")
    monkeypatch.setenv("ACS_RECEIVER_DSN",comm.dsn)
    monkeypatch.setattr("runtime_deployment.receiver_opencode.subprocess.run",lambda *_args,**_kwargs:SimpleNamespace(stdout="fixture-version\n"))
    class NativeFixture(OpenCodeNativeDriver):
        evidence_class="fixture_native_lifecycle"
        def spawn(self,operation):
            self._auth(operation)
            self.session_id="ses_fixture_only"
            return self._receipt("runtime_acknowledged",native_ack_type="fixture")
        def inspect(self,operation):
            self._auth(operation)
            if getattr(self,"uncertain",False):
                raise ClockUncertain("controlled uncertain Authority sample")
            return self._receipt("context_observed",status={"type":"idle"},messages=[])
    monkeypatch.setattr("runtime_deployment.receiver_opencode.OpenCodeNativeDriver",NativeFixture)
    capacity=OpenCodeReceiverCapacity(config,"c"*64,supplied)
    try:
        assert capacity.authority.context.principal_ref==observer.context.principal_ref
        assert capacity.driver.profile.agent is None and capacity.driver.profile.model_id is None
        assert capacity.health()["session_ref"]=="ses_fixture_only"
        assert not hasattr(capacity,"collector")
        capacity.driver.uncertain=True
        uncertain=capacity.health()
        assert uncertain["state"]=="unknown" and uncertain["session_ref"] is None
        assert uncertain["observation"]=="native_readback_unavailable"
        with comm.authority._connect() as connection:
            connection.execute("UPDATE enrolled_runtimes SET status='retired' WHERE runtime_id='runtime'")
        with pytest.raises(AcceptanceGuardFailed,match="enrollment"):
            capacity.health()
    finally:
        capacity.close()


@pytest.mark.skipif(os.getenv("ACS_REAL_OPENCODE_TEST")!="1" or not sys.platform.startswith("linux"),
                    reason="actual local Linux OpenCode lifecycle is opt-in")
def test_real_opencode_factory_prepares_an_actual_session_without_a_model(comm,tmp_path,monkeypatch):
    from runtime.delivery_models import EndpointBindingRequest
    from runtime.delivery_node import LocalNodeEndpoint
    from runtime_tests.test_delivery import command as bind_command

    config,supplied,observer=enrolled_opencode_config(comm,tmp_path)
    supplied["executable"]=os.environ["ACS_REAL_OPENCODE_BINARY"]
    monkeypatch.setenv("ACS_RECEIVER_DSN",comm.dsn)
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT",json.dumps({"mcp":{},"plugin":[],"permission":{"*":"deny"}}))
    capacity=OpenCodeReceiverCapacity(config,"c"*64,supplied)
    facts={}
    try:
        assert capacity.authority.context.principal_ref==observer.context.principal_ref
        actual=capacity.health()
        assert actual["state"]=="idle" and actual["session_ref"].startswith("ses_")
        assert capacity.driver._event_thread is None and not hasattr(capacity,"collector")
        endpoint=LocalNodeEndpoint(capacity.node,"local-scope","slot-b",capacity.adapter)
        comm.dispatcher.service.endpoints["opencode-endpoint"]=endpoint
        comm.authority._delivery_endpoints["opencode-endpoint"]=endpoint
        comm.dispatcher.service.bind_endpoint(bind_command(comm.authority,"message.bind","opencode-endpoint"),
            EndpointBindingRequest(scope_id="local-scope",agent_slot_id="slot-b",expires_at=datetime.now(UTC)+timedelta(minutes=2)))
        result=call(comm,"a","configure_team",members=[{"agent_slot_id":"slot-b","principal_ref":"agent:b","endpoint_id":"opencode-endpoint"}])
        assert result["data"]["native_sessions"][0]["session_ref"]==actual["session_ref"]
        with capacity.journal._connect() as connection:
            requests=[json.loads(row[0]) for row in connection.execute("SELECT body FROM driver_events WHERE kind='http_dispatch'")]
        assert sum(row.get("method")=="POST" and row.get("path")=="/session" for row in requests)==1
        assert not any("prompt_async" in row.get("path","") or row.get("path")=="/event" for row in requests)
        facts={"evidence_class":"production OpenCodeReceiverCapacity and actual OpenCode, no model",
            "native":actual,"native_session_creates":1,"model_turns":0,"collector":False,"event_subscription":False,
            "inherited_agent_and_model":capacity.driver.profile.agent is None and capacity.driver.profile.model_id is None}
    finally:
        capacity.close()
        if capacity.driver.owned is not None:
            facts["owned_process_stop"]=capacity.supervisor.inspect(capacity.driver.owned)
    (tmp_path/"real-opencode-factory.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")


@pytest.mark.skipif(os.getenv("ACS_REAL_OPENCODE_MODEL_TEST")!="1" or not sys.platform.startswith("linux"),
                    reason="actual OpenCode model request with approved isolated Provider is opt-in")
@pytest.mark.parametrize("sender_mode", ["scripted", "codex"])
def test_real_opencode_factory_receives_and_replies_through_its_own_mcp(comm,tmp_path,monkeypatch,sender_mode):
    import shutil
    import subprocess
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import asdict

    from runtime.delivery_models import EndpointBindingRequest
    from runtime.delivery_node import LocalNodeEndpoint
    from runtime_tests.test_communication import await_waiter, prepare_ordinary_agents
    from runtime_tests.test_delivery import command as bind_command

    manager=comm.clients["a"]
    prepare_ordinary_agents(comm,tmp_path)
    comm.clients["manager"]=manager
    config,supplied,_observer=enrolled_opencode_config(comm,tmp_path)
    supplied["executable"]=os.environ["ACS_REAL_OPENCODE_BINARY"]
    label="opencode-cedar-"+uuid.uuid4().hex[:12]
    provider_key=json.loads(Path("/home/d26fo/.codex/auth.json").read_text())["OPENAI_API_KEY"]
    monkeypatch.setenv("ACS_OC_TEST_PROVIDER_KEY",provider_key)
    monkeypatch.setenv("ACS_RECEIVER_DSN",comm.dsn)
    monkeypatch.setenv("ACS_OC_TEST_DSN",comm.dsn)
    monkeypatch.setenv("ACS_OC_TEST_CREDENTIAL",comm.clients["b"].credential_provider())
    surface=tmp_path/"opencode-b-surface.json"
    surface.write_text(json.dumps({"context":asdict(comm.clients["b"].service.context),"delivery_maintenance":"external",
        "dsn_ref":{"kind":"environment","name":"ACS_OC_TEST_DSN"},
        "credential_ref":{"kind":"environment","name":"ACS_OC_TEST_CREDENTIAL"}}))
    surface.chmod(0o600)
    root=Path(__file__).resolve().parents[1]
    from runtime.codex_driver import file_digest
    source_files=[path for directory in (root/"runtime",root/"runtime_deployment") for path in directory.glob("*")
                  if path.suffix in {".py",".sql"}]
    source_files += [Path(__file__),root/"runtime_tests/test_communication.py",root/"docs/runtime/p2-mcp-tool-contract.json"]
    source_manifest={path.relative_to(root).as_posix():file_digest(path) for path in source_files}
    (tmp_path/"source-files.json").write_text(json.dumps(source_manifest,indent=2),encoding="utf-8")
    wrapper=tmp_path/"opencode-b-mcp.py"
    wrapper.write_text("import sys\nsys.path.insert(0,"+repr(str(root))+")\nfrom runtime.project_entry import main\nraise SystemExit(main("+
        repr(["--config",str(surface),"--catalog",str(root/"docs/runtime/p2-mcp-tool-contract.json"),"--profile","engineer"])+"))\n")
    native_config={"model":"acs-test/gpt-6.1-sol","default_agent":"acs-peer","plugin":[],
        "provider":{"acs-test":{"npm":"@ai-sdk/openai-compatible","name":"Isolated approved Provider",
            "options":{"baseURL":"https://api.payapionline.top/v1","apiKey":"{env:ACS_OC_TEST_PROVIDER_KEY}"},
            "models":{"gpt-6.1-sol":{"name":"gpt-6.1-sol"}}}},
        "permission":{"*":"deny","acs_*":"allow"},
        "agent":{"acs-peer":{"mode":"primary","prompt":"You are Agent B, ACS collaborator slot-b in project-alpha. "
            f"The release label for this isolated exercise is {label}. Respond through ACS when contacted. "
            "Use the ACS MCP tools and retain the received reply relationship. Do not inspect or change files.",
            "permission":{"*":"deny","acs_*":"allow"}}},
        "mcp":{"acs":{"type":"local","command":[sys.executable,str(wrapper)],"enabled":True,"timeout":180000}}}
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT",json.dumps(native_config))
    capacity=OpenCodeReceiverCapacity(config,"c"*64,supplied)
    sender_process=None
    try:
        endpoint=LocalNodeEndpoint(capacity.node,"local-scope","slot-b",capacity.adapter)
        comm.dispatcher.service.endpoints["opencode-endpoint"]=endpoint
        comm.authority._delivery_endpoints["opencode-endpoint"]=endpoint
        comm.dispatcher.service.bind_endpoint(bind_command(comm.authority,"message.bind","opencode-endpoint"),
            EndpointBindingRequest(scope_id="local-scope",agent_slot_id="slot-b",expires_at=datetime.now(UTC)+timedelta(minutes=5)))
        call(comm,"manager","configure_team",prepare_native=False,
            members=[{"agent_slot_id":"slot-b","principal_ref":"agent:b","endpoint_id":"opencode-endpoint"}])
        started=time.monotonic()
        if sender_mode=="scripted":
            sent=call(comm,"a","send_message",to="collaborator:project-alpha:slot-b",
                      content="What is the release label for this isolated exercise? Please reply through ACS.")["data"]
            with ThreadPoolExecutor(max_workers=1) as pool:
                waiting=pool.submit(call,comm,"a","wait_for_response",handles=[sent["message_handle"]],timeout_seconds=180)
                await_waiter(comm)
                dispatched=comm.dispatcher.dispatch({"tenant_id":comm.authority.tenant_id,
                    "message_id":sent["message_id"],"operation_id":sent["operation_id"]})
                assert dispatched["status"] in {"delivered","uncertain"},dispatched
                observed=waiting.result(timeout=190)
        else:
            binary=shutil.which("codex")
            assert binary,"an actual local Codex CLI is required for the dual-model case"
            a_home=tmp_path/"codex-a"
            a_home.mkdir(mode=0o700)
            a_config=['model="gpt-6.1-sol"','model_provider="acs-test"','approval_policy="never"','sandbox_mode="read-only"',
                'project_doc_max_bytes=0','[features]','apps=false','plugins=false','[model_providers.acs-test]',
                'name="Approved isolated Provider"','base_url="https://api.payapionline.top/v1"','env_key="ACS_A_PROVIDER_KEY"',
                'wire_api="responses"','requires_openai_auth=true']
            for path in sorted((Path.home()/".agents/skills").glob("*/SKILL.md")):
                a_config.extend(['[[skills.config]]','path='+json.dumps(str(path.resolve())),'enabled=false'])
            (a_home/"config.toml").write_text("\n".join(a_config)+"\n")
            a_surface=tmp_path/"codex-a-surface.json"
            a_surface.write_text(json.dumps({"context":asdict(comm.clients["a"].service.context),"delivery_maintenance":"external",
                "dsn_ref":{"kind":"environment","name":"ACS_A_TEST_DSN"},
                "credential_ref":{"kind":"environment","name":"ACS_A_TEST_CREDENTIAL"}}))
            a_surface.chmod(0o600)
            a_wrapper=tmp_path/"codex-a-mcp.py"
            a_wrapper.write_text("import sys\nsys.path.insert(0,"+repr(str(root))+")\nfrom runtime.project_entry import main\nraise SystemExit(main("+
                repr(["--config",str(a_surface),"--catalog",str(root/"docs/runtime/p2-mcp-tool-contract.json"),"--profile","engineer"])+"))\n")
            # B's private initial label/configuration and MCP credential must
            # never be inherited by A. Both model contexts know only their role.
            a_env={key:value for key,value in os.environ.items() if not key.startswith(("OPENCODE_","ACS_OC_","ACS_RECEIVER_","CODEX_"))}
            a_env.update(CODEX_HOME=str(a_home),ACS_A_PROVIDER_KEY=provider_key,ACS_A_TEST_DSN=comm.dsn,
                         ACS_A_TEST_CREDENTIAL=comm.clients["a"].credential_provider())
            declaration="mcp_servers={acs={command="+json.dumps(sys.executable)+",args=["+json.dumps(str(a_wrapper))+"]," \
                'env_vars=["ACS_A_TEST_DSN","ACS_A_TEST_CREDENTIAL"],required=true,startup_timeout_sec=30,tool_timeout_sec=180,' \
                'tools={send_message={approval_mode="approve"}}}}'
            with (tmp_path/"codex-a.jsonl").open("w") as output,(tmp_path/"codex-a.stderr").open("w") as errors:
                sender_process=subprocess.Popen([binary,"exec","--ephemeral","--json","--skip-git-repo-check","--sandbox","read-only",
                    "-C",str(tmp_path),"-c",declaration,
                    ("You are ordinary Agent A in ACS project-alpha. Use ACS MCP to ask collaborator slot-b for the release label of this "
                    "isolated exercise. The normal ACS send defaults can activate B. Wait for B's actual ACS reply and report its exact label. "
                    "Use the configured ACS MCP tools; do not inspect or change files.")],env=a_env,stdin=subprocess.DEVNULL,stdout=output,stderr=errors)
            deadline=time.monotonic()+150
            while True:
                with comm.authority._connect() as connection:
                    committed=connection.execute("SELECT message_id,operation_id FROM delivery_messages WHERE tenant_id=%s "
                        "AND packet_json->>'sender'='collaborator:project-alpha:slot-a-real'",(comm.authority.tenant_id,)).fetchone()
                if committed:
                    break
                assert sender_process.poll() is None and time.monotonic()<deadline,"Codex A did not submit; see its raw log"
                time.sleep(.2)
            sent={"message_id":committed[0],"operation_id":committed[1],"message_handle":"message:project-alpha:"+committed[0]}
            dispatched=comm.dispatcher.dispatch({"tenant_id":comm.authority.tenant_id,**{key:sent[key] for key in ("message_id","operation_id")}})
            assert dispatched["status"] in {"delivered","uncertain"},dispatched
            assert sender_process.wait(timeout=210)==0,"Codex A did not complete; see its raw log"
            assert label in (tmp_path/"codex-a.jsonl").read_text()
            observed=call(comm,"a","wait_for_response",handles=[sent["message_handle"]],timeout_seconds=0)
        assert observed["state"]=="satisfied",observed
        reply=observed["data"]["observations"][0]["reply"]
        assert reply["from"]=="collaborator:project-alpha:slot-b" and label in reply["content"]
        with capacity.journal._connect() as connection:
            requests=[json.loads(row[0]) for row in connection.execute("SELECT body FROM driver_events WHERE kind='http_dispatch'")]
        prompts=[row for row in requests if row.get("method")=="POST" and "prompt_async" in row.get("path","")]
        assert len(prompts)==1 and not capacity.driver._event_thread
        with comm.authority._connect() as connection:
            assert connection.execute("SELECT count(*) FROM communication_messages").fetchone()[0]==2
            assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0]==1
            assert connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is None
        facts={"evidence_class":"independent Codex A and OpenCode B models" if sender_mode=="codex" else
                                "scripted ordinary A and actual independent OpenCode B model using public MCP",
            "session_id":capacity.driver.session_id,"request":sent,"reply":reply,"prompt_async_count":1,
            "model_elapsed_seconds":time.monotonic()-started,"collector":False,"event_subscription":False,
            "work_table_present":False,"selection":"inherited from isolated OpenCode configuration"}
        assert all(file_digest(root/name)==expected for name,expected in source_manifest.items()),"source changed during actual model test"
        (tmp_path/"opencode-model-facts.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
    finally:
        if sender_process is not None and sender_process.poll() is None:
            sender_process.terminate()
            sender_process.wait(timeout=15)
        capacity.close()
