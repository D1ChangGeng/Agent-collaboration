"""Actual installed Native transport; opt-in and separate from model acceptance."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.delivery_models import EndpointBindingRequest, InvocationRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import prepare_ordinary_agents
from runtime_tests.test_delivery import command

comm = comm_fixture

ROOT = Path(__file__).resolve().parents[1]


def test_native_startup_configuration_is_sealed_without_logging_its_contents(tmp_path):
    from runtime.codex_driver import DriverRejected
    config=tmp_path/"config.toml"
    config.write_text("",encoding="utf-8")
    secret="private-native-setting-for-test"
    profile=LaunchProfile(str(tmp_path/"codex.exe"),"", "native-version", str(tmp_path/"schema.json"),"",
        str(tmp_path),str(tmp_path),"",":read-only",{},execution_mode="native",
        startup_overrides=("developer_instructions="+json.dumps(secret),))
    assert profile.validate() is profile
    recorded=json.dumps(profile.binding())
    assert secret not in recorded and "startup_overrides_sha256" in recorded
    from dataclasses import replace
    with pytest.raises(DriverRejected):
        replace(profile,startup_overrides=("not valid = [",)).validate()


@pytest.mark.skipif(os.getenv("ACS_REAL_NATIVE_TEST") != "1", reason="actual configuration-to-Native probe is opt-in")
def test_configuration_creates_real_session_and_status_reads_never_spawn(comm, tmp_path):
    from runtime_tests.test_communication import call

    binary=shutil.which("codex.exe") if os.name=="nt" else shutil.which("codex")
    if not binary:
        pytest.skip("Codex unavailable")
    version=subprocess.run([binary,"--version"],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
    schema=tmp_path/"schema"
    subprocess.run([binary,"app-server","generate-json-schema","--out",str(schema)],capture_output=True,check=True,timeout=60)
    schema_file=next(schema.glob("*protocol*.json"))
    home=tmp_path/"native-home"
    home.mkdir(mode=0o700)
    config=home/"config.toml"
    config.write_text('approval_policy="never"\nsandbox_mode="read-only"\n[features]\napps=false\nplugins=false\n',encoding="utf-8")
    config.chmod(0o600)
    if os.name=="nt":
        from runtime.supervisor import WindowsJobSupervisor
        supervisor=WindowsJobSupervisor()
    else:
        from runtime.posix_process_supervisor import PosixProcessSupervisor
        supervisor=PosixProcessSupervisor()
    binding=BindingIdentity("config-native-node","config-native-boot","config-native-runtime","config-native-capacity","slot-b",1)
    environment={key:value for key,value in os.environ.items() if key!="CODEX_HOME"}
    profile=LaunchProfile(binary,file_digest(binary),version.removeprefix("codex-cli "),str(schema_file),file_digest(schema_file),
        str(tmp_path),str(home),file_digest(config),":read-only",environment,execution_mode="native")
    def current(operation, identity):
        operation.validate()
        assert identity==binding
    driver=CodexAppServerDriver("config-"+uuid.uuid4().hex,profile,DriverJournal(tmp_path/"driver.sqlite"),
                               identity=binding,check_current=current,supervisor=supervisor)
    def operation(name):
        return AuthorizedOperation("config-native-"+name,"operator-config-command","session-config",
                                   comm.authority.context.grant_ref,datetime.now(UTC)+timedelta(minutes=2))
    configurations=[]
    def prepare():
        configurations.append("prepare")
        return driver.spawn(operation("setup"))
    adapter=NativeDeliveryAdapter(driver,authorize_invocation=lambda invocation,_identity: AuthorizedOperation(
        invocation.invocation_id,invocation.command_id,invocation.message_id,invocation.envelope.grant_ref,None),
        configure_runtime=prepare,inspect_runtime=lambda:driver.inspect(operation("read")))
    node=NodeJournal(tmp_path/"node.sqlite",node_id=binding.node_id,boot_incarnation=binding.node_boot_id)
    endpoint=LocalNodeEndpoint(node,"local-scope","slot-b",adapter)
    comm.dispatcher.service.endpoints["config-native-b"]=endpoint
    comm.authority._delivery_endpoints=comm.dispatcher.service.endpoints
    comm.dispatcher.service.bind_endpoint(command(comm.authority,"message.bind","config-native-b"),
        EndpointBindingRequest(scope_id="local-scope",agent_slot_id="slot-b",expires_at=datetime.now(UTC)+timedelta(hours=1)))
    evidence=ROOT/"integration_evidence/acs-native-20261031"
    evidence.mkdir(parents=True,exist_ok=True)
    try:
        assert driver.thread_id is None
        configured=call(comm,"a","configure_team",members=[{"agent_slot_id":"slot-b","principal_ref":"agent:b","endpoint_id":"config-native-b"}])
        session=configured["data"]["native_sessions"][0]
        assert session["state"]=="native_observed",session
        assert session["session_ref"]==driver.thread_id and configurations==["prepare"]
        for _ in range(2):
            states=call(comm,"a","list_harnesses")["data"]["items"]
            actual=next(item for item in states if item["endpoint_id"]=="config-native-b")
            assert actual["session_ref"]==driver.thread_id and actual["runtime_state"]=="idle"
        assert configurations==["prepare"]
        with driver.journal._connect() as connection:
            events=[json.loads(row[0]) for row in connection.execute("SELECT body FROM driver_events WHERE kind='rpc_dispatch'")]
        assert sum(event.get("method")=="thread/start" for event in events)==1
        assert not any(event.get("method")=="turn/start" for event in events)
        (evidence/"configuration-native-session.json").write_text(json.dumps({"installed_version":version,
            "configuration_result":session,"thread_start_count":1,"model_turn_count":0,"status_queries":2},indent=2),encoding="utf-8")
    finally:
        if driver.owned is not None:
            supervisor.terminate_tree(driver.owned)
        driver.detach_transport()


@pytest.mark.skipif(os.getenv("ACS_REAL_NATIVE_TEST") != "1", reason="actual Native-session probe is opt-in")
def test_actual_codex_session_setup_and_idle_observation_without_model(tmp_path):
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    if binary is None:
        pytest.skip("Codex executable unavailable")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    schema_root = tmp_path / "schema"
    generated = subprocess.run([binary, "app-server", "generate-json-schema", "--out", str(schema_root)],
                               capture_output=True, text=True, check=False, timeout=60)
    assert generated.returncode == 0, generated.stderr
    schemas = list(schema_root.glob("*protocol*.json"))
    assert schemas, "actual Codex binary did not emit its protocol schema"
    selected_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = selected_home / "config.toml"
    if os.name == "nt":
        from runtime.supervisor import WindowsJobSupervisor
        supervisor = WindowsJobSupervisor()
    else:
        from runtime.posix_process_supervisor import PosixProcessSupervisor
        supervisor = PosixProcessSupervisor()
    identity = BindingIdentity("native-probe-node", "native-probe-boot", "native-probe-runtime",
                               "native-probe-capacity", "native-probe-slot", 1)
    profile = LaunchProfile(binary, file_digest(binary), version.removeprefix("codex-cli "),
        str(schemas[0]), file_digest(schemas[0]), str(tmp_path), str(selected_home),
        file_digest(config) if config.exists() else "", ":read-only", dict(os.environ), execution_mode="native",
        startup_overrides=("project_doc_max_bytes=0", "mcp_servers={}"))
    def current(operation, binding):
        operation.validate()
        assert binding == identity
    driver = CodexAppServerDriver("probe-" + uuid.uuid4().hex, profile, DriverJournal(tmp_path / "driver.sqlite"),
                                  identity=identity, check_current=current, supervisor=supervisor, rpc_timeout=30)
    def operation(action):
        return AuthorizedOperation("native-probe-" + action, "probe-command-" + action, "setup-" + action,
                                   "operator-native-probe", datetime.now(UTC)+timedelta(minutes=2))
    facts = {"installed_version": version, "model_turns_requested": 0}
    evidence = ROOT / "integration_evidence/acs-native-20261031"
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        receipt = driver.spawn(operation("setup"))
        assert driver.thread_id and receipt["thread_id"] == driver.thread_id
        view = driver.inspect(operation("observe"))
        assert view["thread"]["id"] == driver.thread_id
        facts.update(thread_id=driver.thread_id, session_id=driver.session_id, observation="real Native setup and read")
    finally:
        if driver.owned is not None:
            proof = supervisor.terminate_tree(driver.owned)
            facts["owned_process_stop_verified"] = proof["verified"]
        driver.detach_transport()
        (evidence / "native-session-no-model.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.getenv("ACS_REAL_AGENT_TEST") != "1", reason="actual Native-triggered A/B experiment is opt-in")
@pytest.mark.parametrize("scenario", ["reply", "notice"])
def test_real_default_invoke_activates_b_and_b_replies_through_its_own_mcp(comm, tmp_path, monkeypatch, scenario):
    """The production dispatcher/Native Adapter starts B's first model turn.

    The reply case uses ordinary A/B contexts; the notice case uses an ordinary
    sender and its recipient's configured manager. No evaluator forwards content,
    supplies reply IDs or projects native final output.
    """
    import asyncio
    from contextlib import suppress
    from copy import copy
    from dataclasses import replace

    from runtime.communication_dispatch import maintain_communication_deliveries
    from runtime.models import CommandEnvelope
    from runtime_tests.test_communication import call, wait

    manager_client = comm.clients["a"]
    prepare_ordinary_agents(comm, tmp_path)
    system_notice = scenario == "notice"
    use_factory = os.getenv("ACS_NATIVE_FACTORY_TEST") == "1"
    if system_notice:
        from runtime.auth import LocalCredentialAuthenticator
        from runtime.delivery_node import InvocationPreCallRejected
        from runtime.domain import DomainAuthority
        from runtime.mcp_runtime import McpRuntime
        from runtime.project_service import ProjectService
        from runtime.surfaces import SharedService
        from runtime_tests.test_communication import CATALOG
        comm.clients["manager"] = manager_client
        configured = call(comm, "manager", "configure_team", prepare_native=False,
            members=[{"agent_slot_id": "slot-b", "principal_ref": "agent:b", "role": "route"}])["data"]["caller_bindings"][0]
        previous = comm.clients["b"]
        ctx = replace(previous.service.context, grant_ref=configured["grant_ref"])
        comm.clients["b"] = McpRuntime(ProjectService(SharedService(DomainAuthority(comm.dsn, context=ctx),
            LocalCredentialAuthenticator(ctx)), CATALOG, profile="route_manager"), previous.credential_provider)
        call(comm, "b", "configure_team", prepare_native=False,
             members=[{"agent_slot_id": "slot-c", "principal_ref": "agent:c"}])
        def unreachable(_invocation):
            raise InvocationPreCallRejected("isolated child receiver cannot accept a Native call")
        comm.drivers["c"].prepare = unreachable
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    if not binary:
        pytest.skip("Codex unavailable")
    selected_home = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex")))
    version = subprocess.run([binary,"--version"],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
    evidence_root = ROOT / "integration_evidence/acs-native-20261031"
    evidence = evidence_root / (("notice-" if system_notice else "invoke-")+uuid.uuid4().hex[:12])
    evidence.mkdir(parents=True, exist_ok=True)
    source_files = [path for directory in (ROOT/"runtime", ROOT/"runtime_deployment")
                    for path in directory.glob("*") if path.suffix in {".py", ".sql"}]
    source_files += [ROOT/"docs/runtime/p2-mcp-tool-contract.json", Path(__file__),
                     ROOT/"runtime_tests/test_communication.py", ROOT/"runtime_tests/test_communication_receiver.py"]
    source_manifest = {str(path.relative_to(ROOT)).replace("\\", "/"): file_digest(path) for path in source_files}
    (evidence/"source-files.json").write_text(json.dumps(source_manifest,indent=2),encoding="utf-8")
    (evidence_root/"latest-invoke.json").write_text(json.dumps({"directory":str(evidence)}),encoding="utf-8")
    label = "native-orchid-" + uuid.uuid4().hex[:12]
    base_environment = dict(os.environ)
    for field in ("CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        base_environment.pop(field, None)
    provider = os.getenv("ACS_REAL_NATIVE_PROVIDER")
    import tomllib
    selected_config = tomllib.loads((selected_home/"config.toml").read_text(encoding="utf-8"))
    def isolated_native_home(name):
        directory = tmp_path / (name+"-codex-home")
        directory.mkdir(mode=0o700)
        selected_provider = provider or selected_config.get("model_provider", "openai")
        values = ["model="+json.dumps(selected_config.get("model", "gpt-6.1-sol")),
                  "model_provider="+json.dumps(selected_provider), "approval_policy=\"never\"", "sandbox_mode=\"read-only\"",
                  "project_doc_max_bytes=0", "[features]", "apps=false", "plugins=false"]
        if selected_provider in selected_config.get("model_providers", {}):
            values.append("[model_providers."+selected_provider+"]")
            for key in ("name","base_url","env_key","wire_api","requires_openai_auth","supports_websockets"):
                value = selected_config["model_providers"][selected_provider].get(key)
                if value is not None:
                    values.append(key+"="+(str(value).lower() if isinstance(value,bool) else json.dumps(value)))
        # Personal skills are discovered outside CODEX_HOME. Keep the model
        # experiment on its declared tool surface, using the supported per-skill
        # switch in this test home only. Installed skills/defaults stay intact.
        for path in sorted((Path.home()/".agents/skills").glob("*/SKILL.md")):
            values.extend(["[[skills.config]]", "path="+json.dumps(str(path.resolve())), "enabled=false"])
        path = directory / "config.toml"
        path.write_text("\n".join(values)+"\n",encoding="utf-8")
        path.chmod(0o600)
        return directory
    a_home, b_home = isolated_native_home("a"), isolated_native_home("b")

    def actor_configuration(name):
        client = comm.clients[name]
        path = tmp_path / f"native-{name}-surface.json"
        path.write_text(json.dumps({"context": asdict(client.service.context), "delivery_maintenance": "external",
            "dsn_ref": {"kind":"environment","name":"ACS_NATIVE_TEST_DSN"},
            "credential_ref":{"kind":"environment","name":"ACS_NATIVE_TEST_CREDENTIAL"}}),encoding="utf-8")
        path.chmod(0o600)
        wrapper = tmp_path / f"native-{name}-mcp.py"
        wrapper.write_text("import sys\nsys.path.insert(0,"+repr(str(ROOT))+")\nfrom runtime.project_entry import main\n"
            "raise SystemExit(main("+repr(["--config",str(path),"--catalog",str(ROOT/"docs/runtime/p2-mcp-tool-contract.json"),
                                           "--profile",client.service.profile])+"))\n",encoding="utf-8")
        declaration = "mcp_servers={acs={command="+json.dumps(sys.executable)+",args=["+json.dumps(str(wrapper))+"],"
        declaration += 'env_vars=["ACS_NATIVE_TEST_DSN","ACS_NATIVE_TEST_CREDENTIAL"],required=true,startup_timeout_sec=30,tool_timeout_sec=180,'
        declaration += 'tools={send_message={approval_mode="approve"}}}}'
        environment = dict(base_environment, ACS_NATIVE_TEST_DSN=comm.dsn, ACS_NATIVE_TEST_CREDENTIAL=client.credential_provider())
        overrides = ["project_doc_max_bytes=0", declaration]
        if provider:
            overrides.append("model_provider="+json.dumps(provider))
        return environment, overrides

    b_environment, b_overrides = actor_configuration("b")
    b_instructions = ("You are manager B, collaborator slot-b in ACS project-alpha. When ACS reports a communication "
        "obstacle, check the notification's current Native delivery state from ACS; the inline obstacle describes "
        "only the original message. For this isolated exercise, report your observation "
        "in this Native Session; do not send an Agent message or try to repair the receiver. Do not inspect or change files."
        if system_notice else
        "You are Agent B, collaborator slot-b in ACS project-alpha. For this isolated exercise the release label is "
        +label+". Respond to the other Agent through ACS when contacted. Do not inspect or change files.")
    b_overrides.append("developer_instructions="+json.dumps(b_instructions))
    schema = tmp_path / "actual-schema"
    subprocess.run([binary,"app-server","generate-json-schema","--out",str(schema)],capture_output=True,check=True,timeout=60)
    schema_file = next(schema.glob("*protocol*.json"))
    if os.name == "nt":
        from runtime.supervisor import WindowsJobSupervisor
        supervisor = WindowsJobSupervisor()
    else:
        from runtime.posix_process_supervisor import PosixProcessSupervisor
        supervisor = PosixProcessSupervisor()
    binding = BindingIdentity("native-b-node", "native-b-boot-"+uuid.uuid4().hex, "native-b-runtime",
                              "native-b-capacity", "slot-b", 1)
    lifecycle = {"native-b-session-setup", "native-b-session-close"}
    def validate_current(operation, observed):
        operation.validate()
        assert observed == binding
        if operation.operation_id in lifecycle:
            return
        with comm.authority._connect() as connection:
            row = connection.execute("SELECT a.invocation_json,m.command_json FROM delivery_attempts a "
                "JOIN delivery_messages m USING(tenant_id,message_id) WHERE a.tenant_id=%s "
                "AND a.invocation_json->>'invocation_id'=%s", (comm.authority.tenant_id, operation.operation_id)).fetchone()
            assert row, "Native operation must originate in the committed delivery ledger"
            invocation = InvocationRequest.model_validate_json(json.dumps(row[0]),strict=True)
            original = CommandEnvelope.model_validate_json(json.dumps(row[1]),strict=True)
            assert invocation.command_id == operation.command_id and invocation.message_id == operation.message_id
            assert invocation.envelope.packet.target_agent_slot_id == "slot-b"
            actor = copy(comm.authority)
            actor.context = replace(comm.authority.context, principal_ref=original.principal_ref, grant_ref=original.grant_ref)
            actor._authorize(original, connection.cursor(), "runtime.invoke", "local-scope")
    config = b_home/"config.toml"
    profile = LaunchProfile(binary,file_digest(binary),version.removeprefix("codex-cli "),str(schema_file),file_digest(schema_file),
        str(tmp_path),str(b_home),file_digest(config),":read-only",{k:v for k,v in b_environment.items() if k!="CODEX_HOME"},
        execution_mode="native",startup_overrides=tuple(b_overrides))
    capacity = None
    if use_factory:
        from runtime_tests.test_communication_receiver import enrolled_native_factory
        supervisor.close()
        overlays = [value for value in b_overrides if value.startswith(("mcp_servers=", "developer_instructions="))]
        config.write_text("\n".join(overlays)+"\n"+config.read_text(encoding="utf-8"),encoding="utf-8")
        for name in ("ACS_NATIVE_TEST_DSN", "ACS_NATIVE_TEST_CREDENTIAL"):
            monkeypatch.setenv(name, b_environment[name])
        capacity = enrolled_native_factory(comm, tmp_path, monkeypatch, b_home)
        driver, supervisor, binding = capacity.driver, capacity.supervisor, capacity.binding
    else:
        driver = CodexAppServerDriver("native-real-b-"+uuid.uuid4().hex,profile,DriverJournal(tmp_path/"real-b-driver.sqlite"),
            identity=binding,check_current=validate_current,supervisor=supervisor,rpc_timeout=30)
    def lifecycle_operation(name):
        return AuthorizedOperation("native-b-session-"+name,"native-b-setup-command","native-b-setup",
                                   comm.authority.context.grant_ref,datetime.now(UTC)+timedelta(minutes=6))
    process = None
    try:
        if not use_factory:
            driver.spawn(lifecycle_operation("setup"))
        assert driver.thread_id
        skills = driver.client.request("skills/list", {"cwds": [str(tmp_path)], "forceReload": True})
        personal_root = (Path.home()/".agents/skills").resolve()
        personal_skills = [skill for group in skills.get("data", []) for skill in group.get("skills", [])
                           if Path(skill["path"]).resolve().is_relative_to(personal_root)]
        assert not any(skill["enabled"] for skill in personal_skills), "personal skill isolation was not adopted"
        lose_ack=os.getenv("ACS_NATIVE_ACK_LOSS")=="1"
        if lose_ack:
            from runtime.codex_driver import OutcomeUncertain
            original_request=driver.client.request
            def lose_native_ack(method, params, **kwargs):
                response=original_request(method,params,**kwargs)
                if method=="turn/start":
                    raise OutcomeUncertain("injected observation loss after actual Native turn/start response")
                return response
            driver.client.request=lose_native_ack
        def authorize_invocation(invocation, observed):
            operation = AuthorizedOperation(invocation.invocation_id,invocation.command_id,invocation.message_id,
                                             invocation.envelope.grant_ref,invocation.envelope.packet.deadline)
            validate_current(operation,observed)
            return operation
        adapter = capacity.adapter if use_factory else NativeDeliveryAdapter(driver,authorize_invocation=authorize_invocation)
        node = capacity.node if use_factory else NodeJournal(tmp_path/"real-b-node.sqlite",node_id=binding.node_id,boot_incarnation=binding.node_boot_id)
        endpoint = LocalNodeEndpoint(node,"local-scope","slot-b",adapter)
        selected_endpoint = "factory-b" if use_factory else "endpoint-b"
        comm.dispatcher.service.endpoints[selected_endpoint] = endpoint
        comm.authority._delivery_endpoints = comm.dispatcher.service.endpoints
        comm.dispatcher.service.bind_endpoint(command(comm.authority,"message.bind",selected_endpoint,revision=0 if use_factory else 1),
            EndpointBindingRequest(scope_id="local-scope",agent_slot_id="slot-b",expires_at=datetime.now(UTC)+timedelta(hours=1)))
        if use_factory:
            comm.clients["factory-manager"] = manager_client
            call(comm,"factory-manager","configure_team",prepare_native=False,
                 members=[{"agent_slot_id":"slot-b","principal_ref":"agent:b","endpoint_id":selected_endpoint}])
        a_environment, a_overrides = actor_configuration("a")
        a_environment["CODEX_HOME"] = str(a_home)
        arguments=[binary,"exec","--ephemeral","--json","--skip-git-repo-check","--sandbox","read-only","-C",str(tmp_path)]
        for override in a_overrides:
            arguments.extend(["-c",override])
        arguments.append("You are Agent A. Use ACS project-alpha to contact collaborator slot-c once about the release label "
            "of this isolated exercise. Report whether your message submission was accepted; you need not wait for a reply. "
            "Use ACS; do not inspect or change files." if system_notice else
            "You are Agent A. Use ACS project-alpha to ask collaborator slot-b for the release label of this isolated exercise. "
            "B has an idle Native Session and ACS can activate it with the normal send defaults. Stay with the exchange until you receive "
            "B's answer, then report the exact label. Use ACS; do not inspect or change files.")
        with (evidence/"native-agent-a.jsonl").open("w",encoding="utf-8") as out,(evidence/"native-agent-a.stderr.txt").open("w",encoding="utf-8") as err:
            process=subprocess.Popen(arguments,env=a_environment,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        observed_notice_calls = []
        async def run():
            task=asyncio.create_task(maintain_communication_deliveries(comm.clients["a"].service.service))
            comm.clients["a"].service.service.authority._delivery_endpoints=comm.authority._delivery_endpoints
            try:
                end=time.monotonic()+240
                while time.monotonic()<end:
                    if system_notice:
                        # Observe actual tool completion events. A fresh Codex
                        # rollout can briefly be empty during its first write;
                        # the evaluator must not abort that in-flight invocation.
                        with driver._lock:
                            driver._drain("notice-test-observer")
                        with driver.journal._connect() as connection:
                            events = [json.loads(row[0]).get("message", {}) for row in connection.execute(
                                "SELECT body FROM driver_events WHERE kind='native_event'")]
                        observed_notice_calls[:] = [event.get("params", {}).get("item", {}) for event in events
                            if event.get("method") == "item/completed"]
                        observed_notice_calls[:] = [item for item in observed_notice_calls
                            if item.get("type") == "mcpToolCall" and item.get("server") == "acs"
                            and item.get("tool") == "read_message" and item.get("status") == "completed"
                            and str(item.get("arguments", {}).get("handle", "")).startswith("notification:")]
                    native_finished = system_notice and any(event.get("method") == "turn/completed" for event in events)
                    if process.poll() is not None and (not system_notice or observed_notice_calls or native_finished):
                        break
                    await asyncio.sleep(0.5)
                assert process.poll()==0,"A failed or did not finish; see native-agent-a logs"
                if system_notice:
                    (evidence/"manager-notice-tool-observations.json").write_text(json.dumps(observed_notice_calls,indent=2),encoding="utf-8")
                    assert observed_notice_calls,"Native manager has not actually read the system notification"
                    result = observed_notice_calls[0].get("result", {})
                    body = result.get("structuredContent")
                    if body is None:
                        body = json.loads(next(block["text"] for block in result.get("content", []) if block.get("type") == "text"))
                    assert body["ok"] and body["data"]["source"] == "acs", body
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        asyncio.run(run())
        with psycopg.connect(comm.dsn) as connection:
            messages=connection.execute("SELECT c.message_id,c.sender,c.recipient,m.packet_json->>'content',m.packet_json->>'activation' "
                "FROM communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) ORDER BY c.sequence").fetchall()
            relations=connection.execute("SELECT request_id,reply_id FROM communication_replies").fetchall()
            work_table_present = connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is not None
            assert not work_table_present
            work_count = 0
        with driver.journal._connect() as connection:
            turns=connection.execute("SELECT body FROM driver_events WHERE kind='rpc_dispatch'").fetchall()
        native_turns=[json.loads(row[0]) for row in turns if json.loads(row[0]).get("method")=="turn/start"]
        facts={"installed_version":version,"b_native_thread":driver.thread_id,"messages":messages,"reply_relationships":relations,
            "native_turn_start_count":len(native_turns),"work_count":work_count,"label":label,"activation":"production dispatcher and NativeDeliveryAdapter",
            "fault_injection":"observation loss after actual Native response" if lose_ack else None,
            "source_manifest_sha256":file_digest(evidence/"source-files.json"),
            "production_receiver_factory":use_factory,
            "work_table_present": work_table_present,
            "personal_skill_readback": {"discovered": len(personal_skills), "enabled": 0},
            "collector_created":hasattr(capacity,"collector") if capacity else False}
        assert all(file_digest(ROOT/name)==hashed for name,hashed in source_manifest.items()), "Source changed during live acceptance"
        (evidence/"native-invoke-facts.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
        assert messages[0][4]=="invoke" and len(native_turns)==1 and work_count==0
        if system_notice:
            assert len(messages)==1 and messages[0][2].endswith(":slot-c") and relations==[]
            assert comm.drivers["c"].calls==[] and comm.drivers["a"].calls==[]
            assert wait(comm,"a","message:project-alpha:"+messages[0][0])["state"]=="timeout"
            notice = call(comm,"b","read_message",handle=observed_notice_calls[0]["arguments"]["handle"])["data"]
            assert notice["source"]=="acs" and notice["code"]=="native_pre_call_rejected"
            facts.update(system_notification=notice,manager_read_tool_count=len(observed_notice_calls),
                         original_request_received_no_agent_reply=True)
            (evidence/"native-invoke-facts.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
        else:
            assert relations
        if lose_ack:
            with psycopg.connect(comm.dsn) as connection:
                committed=connection.execute("SELECT operation_id,state FROM delivery_messages WHERE message_id=%s",(messages[0][0],)).fetchone()
            assert committed[1]=="uncertain"
            replay_states=[]
            for _ in range(2):
                repeated=comm.dispatcher.dispatch({"tenant_id":comm.authority.tenant_id,"message_id":messages[0][0],"operation_id":committed[0]})
                assert repeated["status"]=="uncertain"
                replay_states.append(repeated["status"])
            with driver.journal._connect() as connection:
                count=sum(json.loads(row[0]).get("method")=="turn/start" for row in connection.execute("SELECT body FROM driver_events WHERE kind='rpc_dispatch'"))
            assert count==1
            facts.update(authority_native_state=committed[1],replay_states=replay_states,post_retry_native_turn_start_count=count)
            (evidence/"native-invoke-facts.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
        if not system_notice:
            assert any(row[1].endswith(":slot-b") and label in row[3] for row in messages)
        transcript=(evidence/"native-agent-a.jsonl").read_text(encoding="utf-8")
        if not system_notice:
            assert label in transcript
        calls=[json.loads(line) for line in transcript.splitlines() if line.startswith('{')]
        assert all(row['item'].get('server')=='acs' for row in calls if row.get('item',{}).get('type')=='mcp_tool_call'), \
            "Isolated acceptance must not contact inherited App/MCP connections"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if capacity is not None:
            capacity.close()
        elif driver.owned is not None:
            supervisor.terminate_tree(driver.owned)
        driver.detach_transport()
