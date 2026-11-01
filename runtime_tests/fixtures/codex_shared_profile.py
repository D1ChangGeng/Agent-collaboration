"""Isolated, binary-pinned Codex Shared qualification profile (no user config)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from runtime.codex_driver import file_digest
from runtime.communication_tools import NATIVE_COLLABORATION_TOOLS


def configure(state, work, wrapper, request, settings):
    home = state / "codex-home"
    home.mkdir(mode=0o700)
    (state / "tmp").mkdir(mode=0o700)
    binary = request["binary"]
    observed = subprocess.check_output([binary, "--version"], text=True).strip()
    assert observed == "codex-cli 0.163.0", observed
    schema_dir = state / "protocol"
    subprocess.run([binary, "app-server", "generate-json-schema", "--experimental", "--out", str(schema_dir)],
                   check=True, capture_output=True, timeout=60)
    schema = schema_dir / "codex_app_server_protocol.schemas.json"
    # This manifest identifies the binary's built-in catalog; no replacement
    # model_catalog_json is configured or silently synthesized for the Harness.
    catalog = state / "builtin-model-catalog.json"
    catalog.write_text(json.dumps({"source": "binary-builtin", "model": "gpt-6.1-sol",
                                   "executable_sha256": file_digest(binary)}))
    quote = json.dumps
    rows = [
        'model="gpt-6.1-sol"', 'model_reasoning_effort="low"', 'model_provider="acs-test"',
        'approval_policy="never"', 'default_permissions="achp-engineer"',
        'project_doc_max_bytes=0', 'allow_login_shell=false', 'web_search="disabled"',
        'developer_instructions=' + quote(
            "You are ordinary Agent B, slot-b in ACS project-alpha. The release label is "
            + request["label"] + ". Reply to your contact through ACS using the received reply relationship. "
            "Use only ACS tools. Do not inspect files or run commands."),
        '[features]',
        *[name + '=false' for name in ("multi_agent", "multi_agent_v2", "shell_tool",
                                       "request_permissions_tool", "apps", "plugins", "recommended_plugins")],
        '[permissions.achp-engineer.filesystem]', '":minimal"="read"',
        quote(str(work)) + '="read"', quote(binary) + '="read"',
        '[permissions.achp-engineer.network]', 'enabled=false',
        '[model_providers.acs-test]', 'name="Approved isolated Provider"',
        'base_url="https://api.payapionline.top/v1"', 'env_key="ACS_B_PROVIDER_KEY"',
        'wire_api="responses"', 'requires_openai_auth=false', 'supports_websockets=false',
        '[mcp_servers.acs]', 'command=' + quote(sys.executable),
        'args=' + quote(["-I", str(wrapper)]),
        'env_vars=["ACS_B_DSN","ACS_B_CREDENTIAL"]', 'required=true',
        'startup_timeout_sec=90', 'tool_timeout_sec=360',
        'enabled_tools=' + quote(list(NATIVE_COLLABORATION_TOOLS)),
        '[mcp_servers.acs.tools.send_message]', 'approval_mode="approve"',
    ]
    config = home / "config.toml"
    config.write_text("\n".join(rows) + "\n")
    config.chmod(0o600)
    environment_dir = Path(f"/run/user/{os.getuid()}/acs-receiver-codex/receiver-run-" + request["shared_run"] + "/systemd-env")
    environment_dir.mkdir(mode=0o700, parents=True)
    for key in ("home", "temp_root"):
        settings.pop(key)
    settings.update(
        schema_version="acs-receiver-codex-factory/1", codex_version="0.163.0",
        executable_sha256=file_digest(binary), protocol_schema=str(schema),
        protocol_schema_sha256=file_digest(schema), model_catalog=str(catalog),
        model_catalog_sha256=file_digest(catalog), codex_home=str(home),
        config_sha256=file_digest(config), permission_profile="achp-engineer", model="gpt-6.1-sol",
        source_commit=request["source_commit"], source_tree=request["source_tree"],
        systemd_environment_dir=str(environment_dir), collaboration_server="acs",
        environment_refs={name: {"kind": "environment", "name": name}
                          for name in ("ACS_B_DSN", "ACS_B_CREDENTIAL", "ACS_B_PROVIDER_KEY")},
    )
    for prefix in ("spawn", "close"):
        for kind in ("operation", "command", "message"):
            settings[prefix + "_" + kind + "_id"] = request["shared_run"] + ":" + prefix + ":" + kind
    return settings


def sandbox_probe(capacity, state):
    """Exercise the actual permission executor without adding model tools."""
    cwd = Path(capacity.settings["cwd"])
    allowed, blocked, outside = cwd / "allowed.txt", cwd / "blocked.txt", state / "outside.txt"
    allowed.write_text("synthetic allowed read")
    outside.write_text("synthetic private outside read")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"network positive")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def execute(command):
        return capacity.driver.client.request("command/exec", {"command": command, "cwd": str(cwd),
            "permissionProfile": "achp-engineer", "timeoutMs": 10000}, timeout=15)

    try:
        import urllib.request
        url = f"http://127.0.0.1:{server.server_port}/"
        assert urllib.request.urlopen(url, timeout=5).read() == b"network positive"
        read = execute(["/bin/cat", str(allowed)])
        write = execute(["/bin/sh", "-c", "echo forbidden > " + str(blocked)])
        private_read = execute(["/bin/cat", str(outside)])
        network = execute(["/usr/bin/python3", "-I", "-c", "import urllib.request;urllib.request.urlopen(" + repr(url) + ",timeout=2).read()"])
        assert read["exitCode"] == 0 and read["stdout"] == "synthetic allowed read", read
        assert write["exitCode"] != 0 and "Read-only file system" in write["stderr"] and not blocked.exists(), write
        assert private_read["exitCode"] != 0 and "synthetic private" not in private_read["stdout"], private_read
        assert network["exitCode"] != 0 and "network positive" not in network["stdout"], network
        return {"allowed_read": True, "write_denied": True, "outside_read_denied": True,
                "network_host_positive": True, "network_sandbox_denied": True,
                "executor": "actual command/exec with achp-engineer profile"}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
