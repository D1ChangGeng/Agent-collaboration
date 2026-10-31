"""Opt-in ordinary Windows Codex <-> Linux OpenCode using real ACS tools.

This qualifies message_only across machines, independently of Native launch.
The controller starts B after commit and supplies neither message body nor ID.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import uuid
from dataclasses import asdict
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime_tests.test_communication import call, prepare_ordinary_agents
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.getenv("ACS_REAL_CROSS_HARNESS_TEST") != "1",
                    reason="cross-host model requests and SSH fixture are explicit opt-in")
def test_ordinary_codex_opencode_exchange_over_ssh(comm, tmp_path):
    host = os.environ["ACS_MATRIX_SSH_HOST"]
    remote_uv = os.environ["ACS_MATRIX_REMOTE_UV"]
    remote_binary = os.environ["ACS_MATRIX_REMOTE_OPENCODE"]
    provider_key = os.environ["ACS_MATRIX_PROVIDER_KEY"]
    binary = shutil.which("codex.exe") if os.name == "nt" else shutil.which("codex")
    assert binary, "installed Codex is required"
    assert host and not host.startswith("-"), "SSH alias required"
    ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]

    def remote(command, *, data=None, timeout=45):
        result = subprocess.run([*ssh, command], input=data, capture_output=True, timeout=timeout, check=False)
        assert result.returncode == 0, result.stderr.decode(errors="replace").replace(provider_key, "[redacted]")[-2000:]
        return result.stdout.decode()

    token = uuid.uuid4().hex
    remote_root = "/tmp/acs-cross-harness-" + token
    evidence = ROOT / "integration_evidence/acs-cross-harness-20261031" / token
    evidence.mkdir(parents=True)
    prepare_ordinary_agents(comm, tmp_path)
    label = "cross-iris-" + uuid.uuid4().hex[:12]
    files = [p for folder in (ROOT / "runtime", ROOT / "runtime_deployment")
             for p in folder.rglob("*") if p.suffix in {".py", ".sql"}]
    files += [ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / "docs/runtime/p2-mcp-tool-contract.json",
              Path(__file__), ROOT / "runtime_tests/test_communication.py"]
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    helper = ROOT / "runtime_tests/fixtures/cross_harness_remote.py"
    manifest["remote_actor.py"] = hashlib.sha256(helper.read_bytes()).hexdigest()
    source_manifest = tmp_path / "source-files.json"
    source_manifest.write_text(json.dumps(manifest, indent=2))
    shutil.copyfile(source_manifest, evidence / "source-files.json")
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as pack:
        for path in files:
            pack.add(path, arcname=path.relative_to(ROOT).as_posix())
        pack.add(helper, arcname="remote_actor.py")
        pack.add(source_manifest, arcname="source-files.json")
    # Unique test-owned directory; formal remote checkout is never switched.
    remote("mkdir -m 700 " + shlex.quote(remote_root))
    uploaded = subprocess.run(["scp", "-q", str(archive), host + ":" + remote_root + "/source.tar"],
                              capture_output=True, timeout=60, check=False)
    assert uploaded.returncode == 0, uploaded.stderr
    remote("tar -xf " + remote_root + "/source.tar -C " + remote_root)
    remote("cd " + remote_root + " && " + shlex.quote(remote_uv) + " sync --frozen --no-dev", timeout=150)
    remote_python = remote_root + "/.venv/bin/python"
    remote_port = int(remote("python3 -c " + shlex.quote(
        "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1])")))
    values = conninfo_to_dict(comm.dsn)
    assert values["host"] == "127.0.0.1" and values["dbname"] == "acs_communication_test"
    remote_dsn = make_conninfo(comm.dsn, port=remote_port)
    tunnel = subprocess.Popen([*ssh[:-1], "-o", "ExitOnForwardFailure=yes", "-N", "-R",
        f"127.0.0.1:{remote_port}:127.0.0.1:{values['port']}", host],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    a = b = None
    handles = []
    try:
        # Establish the transport before starting either model, using the same
        # isolated database/search_path as the public MCP instances.
        probe = "import json,sys,psycopg;r=json.load(sys.stdin);c=psycopg.connect(r['dsn']);print(c.execute('SELECT 1').fetchone()[0]);c.close()"
        for attempt in range(15):
            assert tunnel.poll() is None, "reverse forward exited"
            try:
                assert remote(remote_python + " -c " + shlex.quote(probe),
                              data=json.dumps({"dsn": remote_dsn}).encode()) == "1\n"
                break
            except AssertionError:
                if attempt == 14:
                    raise
                time.sleep(0.3)

        native_home = tmp_path / "a-codex-home"
        native_home.mkdir(mode=0o700)
        selected = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        original_config = tomllib.loads((selected / "config.toml").read_text(encoding="utf-8"))
        provider_name = os.environ["ACS_REAL_NATIVE_PROVIDER"]
        provider = original_config["model_providers"][provider_name]
        assert provider["base_url"] == "https://api.payapionline.top/v1"
        config = ['model="gpt-6.1-sol"', 'model_provider=' + json.dumps(provider_name),
                  'approval_policy="never"', 'sandbox_mode="read-only"', 'project_doc_max_bytes=0',
                  '[features]', 'apps=false', 'plugins=false', '[model_providers.' + provider_name + ']']
        for key in ("name", "base_url", "env_key", "wire_api", "requires_openai_auth", "supports_websockets"):
            if key in provider:
                value = provider[key]
                config.append(key + "=" + (str(value).lower() if isinstance(value, bool) else json.dumps(value)))
        for path in sorted((Path.home()/".agents/skills").glob("*/SKILL.md")):
            config.extend(["[[skills.config]]", "path="+json.dumps(str(path.resolve())), "enabled=false"])
        (native_home / "config.toml").write_text("\n".join(config) + "\n", encoding="utf-8")
        a_client = comm.clients["a"]
        a_surface = tmp_path / "a-surface.json"
        a_surface.write_text(json.dumps({"context": asdict(a_client.service.context), "delivery_maintenance": "external",
            "dsn_ref": {"kind": "environment", "name": "ACS_MATRIX_DSN"},
            "credential_ref": {"kind": "environment", "name": "ACS_MATRIX_CREDENTIAL"}}))
        wrapper = tmp_path / "a-mcp.py"
        wrapper.write_text("import sys\nsys.path.insert(0," + repr(str(ROOT)) + ")\n"
            "from runtime.project_entry import main\nraise SystemExit(main(" + repr([
                "--config", str(a_surface), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
                "--profile", "engineer"]) + "))\n")
        declaration = "mcp_servers={acs={command=" + json.dumps(sys.executable) + ",args=[" + json.dumps(str(wrapper)) + \
            '],env_vars=["ACS_MATRIX_DSN","ACS_MATRIX_CREDENTIAL"],required=true,startup_timeout_sec=30,tool_timeout_sec=180,' \
            'tools={send_message={approval_mode="approve"}}}}'
        env = {key: value for key, value in os.environ.items()
               if key not in {"CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"}}
        env.update(CODEX_HOME=str(native_home), ACS_MATRIX_DSN=comm.dsn,
                   ACS_MATRIX_CREDENTIAL=a_client.credential_provider())
        env[provider["env_key"]] = provider_key
        out = (evidence / "a.jsonl").open("w", encoding="utf-8")
        err = (evidence / "a.stderr.txt").open("w", encoding="utf-8")
        handles.extend([out, err])
        a = subprocess.Popen([binary, "exec", "--ephemeral", "--json", "--skip-git-repo-check",
            "--sandbox", "read-only", "-C", str(tmp_path), "-c", declaration,
            ("You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for the release label of this "
            "isolated exercise. Both agents independently read Inbox; use message_only activation for this exchange. "
            "Wait for B's answer and report the exact label. Use only ACS tools; do not inspect or change files.")],
            env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        end = time.monotonic() + 120
        while not call(comm, "b", "check_inbox")["data"]["items"]:
            assert a.poll() is None and time.monotonic() < end, "A failed to submit; see a.jsonl"
            time.sleep(0.3)
        out_b = (evidence / "remote-controller.jsonl").open("w", encoding="utf-8")
        err_b = (evidence / "remote-controller.stderr.txt").open("w", encoding="utf-8")
        handles.extend([out_b, err_b])
        b = subprocess.Popen([*ssh, remote_python + " " + remote_root + "/remote_actor.py"],
                             stdin=subprocess.PIPE, stdout=out_b, stderr=err_b)
        request = {"provider_key": provider_key, "binary": remote_binary, "dsn": remote_dsn,
            "credential": comm.clients["b"].credential_provider(), "context": asdict(comm.clients["b"].service.context),
            "prompt": "You are ordinary Agent B, collaborator slot-b in ACS project-alpha. The release label for this "
                f"isolated exercise is {label}. Check Inbox and assist A through ACS. Both agents independently read "
                "Inbox; use message_only activation for this exchange. Use only ACS tools; do not inspect or change files."}
        b.stdin.write((json.dumps(request) + "\n").encode())
        b.stdin.flush()
        assert b.wait(timeout=270) == 0, "B failed; see remote-controller and b logs"
        assert a.wait(timeout=180) == 0, "A failed; see a.jsonl"
    finally:
        try:
            if b is not None:
                if b.poll() is None:
                    b.stdin.write(b"stop\n")
                    b.stdin.flush()
                    b.wait(timeout=25)
                b.stdin.close()
                for name in ("b.jsonl", "b.stderr.txt", "b-process-facts.json"):
                    result = subprocess.run(["scp", "-q", host + ":" + remote_root + "/" + name,
                                             str(evidence / name)], capture_output=True, timeout=30, check=False)
                    assert result.returncode == 0, "could not retain remote logs: " + name
        finally:
            try:
                if a is not None and a.poll() is None:
                    a.terminate()
                    a.wait(timeout=15)
            finally:
                tunnel.terminate()
                tunnel.wait(timeout=15)
                for handle in handles:
                    handle.close()
    with psycopg.connect(comm.dsn) as connection:
        messages = connection.execute("SELECT c.message_id,c.sender,c.recipient,m.packet_json->>'content',"
            "m.packet_json->>'activation' FROM communication_messages c JOIN delivery_messages m USING(tenant_id,message_id) "
            "ORDER BY c.sequence").fetchall()
        replies = connection.execute("SELECT request_id,reply_id FROM communication_replies").fetchall()
        work_table_present = connection.execute("SELECT to_regclass('work_items')").fetchone()[0] is not None
        assert not work_table_present
        work_count = 0
    a_events = [json.loads(line) for line in (evidence / "a.jsonl").read_text().splitlines() if line.startswith("{")]
    b_events = [json.loads(line) for line in (evidence / "b.jsonl").read_text().splitlines() if line.startswith("{")]
    a_tools = [event["item"] for event in a_events if event.get("item", {}).get("type") == "mcp_tool_call"]
    b_tools = [event["part"] for event in b_events if event.get("type") == "tool_use"]
    facts = {"source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "remote_root": remote_root, "ssh_host": host, "messages": messages, "reply_relationships": replies,
        "work_count": work_count, "work_table_present": work_table_present, "label": label,
        "actor_profiles": {"a": "engineer", "b": "engineer"},
        "a_tools": [item["tool"] for item in a_tools], "b_tools": [item["tool"] for item in b_tools],
        "native_autoactivation": "not_tested", "transport": "public stdio MCP and loopback SSH reverse forwarding"}
    (evidence / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    assert a_tools and all(item["server"] == "acs" for item in a_tools)
    assert b_tools and all(item["tool"].startswith("acs_") for item in b_tools)
    assert any(item["tool"] == "acs_send_message" for item in b_tools)
    assert len(messages) == 2 and len(replies) == 1 and work_count == 0
    assert all(row[4] == "message_only" for row in messages)
    assert messages[0][1].endswith(":slot-a-real") and messages[1][1].endswith(":slot-b")
    assert label in messages[1][3] and label in (evidence / "a.jsonl").read_text()
    assert not any(driver.calls for driver in comm.drivers.values())
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in manifest.items()
               if name != "remote_actor.py"), "source changed during actual acceptance"
