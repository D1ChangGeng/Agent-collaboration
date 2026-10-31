"""Isolated, owned OpenCode actor for the opt-in cross-machine ACS experiment.

Copied with the measured source into a new /tmp directory. Credentials arrive
on the SSH stdin channel and exist only in child environments. EOF stops the
owned process group; it never signals a process found by name or port.
"""
from __future__ import annotations

import hashlib
import json
import os
import select
import sys
import threading
import time
from pathlib import Path


def main():
    from runtime.posix_process_supervisor import PosixProcessSupervisor

    root = Path(__file__).resolve().parent
    request = json.loads(sys.stdin.readline())
    manifest = json.loads((root / "source-files.json").read_text())
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
               for name, digest in manifest.items()), "transferred source differs"
    home = root / "actor-home"
    home.mkdir(mode=0o700)
    cwd = root / "actor-cwd"
    cwd.mkdir(mode=0o700)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OPENCODE_", "XDG_", "ACS_", "CODEX_"))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
               XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"),
               XDG_STATE_HOME=str(home / "state"), ACS_MATRIX_PROVIDER_KEY=request["provider_key"],
               ACS_MATRIX_DSN=request["dsn"], ACS_MATRIX_CREDENTIAL=request["credential"])
    surface = root / "b-surface.json"
    surface.write_text(json.dumps({"context": request["context"], "delivery_maintenance": "external",
        "dsn_ref": {"kind": "environment", "name": "ACS_MATRIX_DSN"},
        "credential_ref": {"kind": "environment", "name": "ACS_MATRIX_CREDENTIAL"}}))
    surface.chmod(0o600)
    wrapper = root / "b-mcp.py"
    wrapper.write_text("import sys\nsys.path.insert(0," + repr(str(root)) + ")\n"
        "from runtime.project_entry import main\nraise SystemExit(main(" + repr([
            "--config", str(surface), "--catalog", str(root / "docs/runtime/p2-mcp-tool-contract.json"),
            "--profile", "engineer"]) + "))\n")
    config = {"$schema": "https://opencode.ai/config.json", "model": "acs-test/gpt-6.1-sol",
        "provider": {"acs-test": {"npm": "@ai-sdk/openai-compatible", "name": "ACS isolated test",
            "options": {"baseURL": "https://api.payapionline.top/v1",
                        "apiKey": "{env:ACS_MATRIX_PROVIDER_KEY}"},
            "models": {"gpt-6.1-sol": {"name": "gpt-6.1-sol"}}}},
        "plugin": [], "permission": {"*": "deny", "acs_*": "allow"},
        "mcp": {"acs": {"type": "local", "command": [sys.executable, str(wrapper)],
                        "enabled": True, "timeout": 180000}}}
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
    binary = request["binary"]
    import subprocess

    resolved = subprocess.run([binary, "debug", "config", "--pure"], env=env, cwd=cwd,
                              capture_output=True, text=True, check=True, timeout=45)
    actual = json.loads(resolved.stdout)
    assert set(actual.get("provider", {})) == {"acs-test"}, "inherited Provider"
    assert set(actual.get("mcp", {})) == {"acs"} and not actual.get("plugin"), "inherited MCP/plugin"
    assert actual["permission"] == config["permission"], "permission override was not adopted"
    version = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             check=True, timeout=20).stdout.strip()
    supervisor = PosixProcessSupervisor()
    owned = supervisor.launch([binary, "run", "--pure", "--format", "json", request["prompt"]],
                               cwd=str(cwd), env=env, label=root.name)
    assert owned.process.stdin is not None
    owned.process.stdin.close()

    def drain(stream, destination):
        with (root / destination).open("wb") as output:
            while chunk := stream.read(65536):
                output.write(chunk)
                output.flush()

    threads = [threading.Thread(target=drain, args=(owned.process.stdout, "b.jsonl")),
               threading.Thread(target=drain, args=(owned.process.stderr, "b.stderr.txt"))]
    for thread in threads:
        thread.start()
    print(json.dumps({"state": "started", "version": version,
                      "isolation": {"mcp": ["acs"], "plugins": 0, "provider": "acs-test"}}), flush=True)
    reason = "completed"
    controller_error = None
    try:
        end = time.monotonic() + 240
        while owned.process.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.25)
            if ready and sys.stdin.readline() in ("", "stop\n"):
                reason = "controller_closed"
                break
            if time.monotonic() >= end:
                reason = "bounded_observation_timeout"
                break
    except Exception as error:
        controller_error = type(error).__name__
        reason = "controller_error"
        raise
    finally:
        before_cleanup = owned.process.poll()
        proof = supervisor.terminate_tree(owned)
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads), "log streams did not stop"
        facts = {"reason": reason, "exit_code": owned.process.returncode,
                 "exit_code_before_cleanup": before_cleanup, "controller_error": controller_error,
                 "process_stop": proof, "version": version, "source_files": len(manifest)}
        (root / "b-process-facts.json").write_text(json.dumps(facts, indent=2))
        print(json.dumps(facts), flush=True)
    return 0 if reason == "completed" and owned.process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
