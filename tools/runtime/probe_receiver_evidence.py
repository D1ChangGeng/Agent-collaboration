"""Probe one installed Codex receiver in an isolated home, without a model turn."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.receiver_contract import ReceiverBinding


def probe(binary: Path, scratch: Path, *, observe_input=False) -> dict:
    binary = binary.resolve(strict=True)
    scratch.mkdir(mode=0o700, parents=True)
    home = scratch / "native-home"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text('approval_policy="never"\nsandbox_mode="read-only"\n'
                      '[features]\napps=false\nplugins=false\n', encoding="utf-8")
    config.chmod(0o600)
    # Do not inherit API keys, caller credentials, MCP configuration or a
    # production CODEX_HOME into the isolated process.
    environment = {key: value for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}}
    environment["CODEX_HOME"] = str(home)
    version = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
        check=True, timeout=20, env=environment).stdout.strip().removeprefix("codex-cli ")
    schemas = scratch / "schema"
    subprocess.run([str(binary), "app-server", "generate-json-schema", "--out", str(schemas)],
        capture_output=True, check=True, timeout=60, env=environment)
    schema = next(schemas.glob("*protocol*.json"))
    if os.name == "nt":
        from runtime.supervisor import WindowsJobSupervisor
        supervisor = WindowsJobSupervisor()
    else:
        from runtime.posix_process_supervisor import PosixProcessSupervisor
        supervisor = PosixProcessSupervisor()
    identity = BindingIdentity("evidence-test-node", "evidence-test-boot", "evidence-test-runtime",
                               "evidence-test-capacity", "evidence-test-slot", 1)
    profile = LaunchProfile(str(binary), file_digest(binary), version, str(schema), file_digest(schema),
        str(scratch), str(home), file_digest(config), ":read-only", environment, execution_mode="native",
        startup_overrides=("project_doc_max_bytes=0", "mcp_servers={}"))

    def current(operation, binding):
        operation.validate()
        if binding != identity:
            raise ValueError("test binding changed")

    driver = CodexAppServerDriver("evidence-" + uuid.uuid4().hex, profile,
        DriverJournal(scratch / "driver.sqlite"), identity=identity, check_current=current,
        supervisor=supervisor, rpc_timeout=30)

    def operation(action):
        return AuthorizedOperation("evidence-" + action, "evidence-command-" + action,
            "evidence-message-" + action, "isolated-test-grant", datetime.now(UTC) + timedelta(minutes=2))

    facts = {"evidence_class": "installed_native_protocol_no_model", "harness_version": version,
             "model_turns_requested": 0}
    try:
        driver.spawn(operation("setup"))
        from runtime.native_input_observations import observe_native_input

        adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda *_: None,
            inspect_runtime=lambda: driver.inspect(operation("observe")),
            observe_input=(lambda: observe_native_input(driver, operation("observe-input"))) if observe_input else None)
        binding = ReceiverBinding(receiver_id="isolated-test-receiver",
            actor_address="collaborator:isolated-test:evidence-test-slot", binding_epoch=1,
            provider_generation=None, native_session_ref=None, authority_id="isolated-test-authority",
            authority_incarnation="isolated-test-incarnation", execution_host_ref="isolated-test-host")
        item = adapter.receiver_snapshot(binding)
        repeated = adapter.receiver_snapshot(binding)
        if not item.native_session_ref or item.capability_scope != repeated.capability_scope:
            raise ValueError("receiver scope was not stably observed")
        with driver.journal._connect() as connection:
            dispatches = [json.loads(row[0])["method"] for row in connection.execute(
                "SELECT body FROM driver_events WHERE kind='rpc_dispatch'")]
        if dispatches.count("thread/start") != 1 or "turn/start" in dispatches:
            raise ValueError("readback unexpectedly mutated Native execution")
        facts.update(snapshot=item.model_dump(mode="json"), thread_start_count=1,
                     turn_start_count=0, repeated_snapshot_same_generation=True, status="passed")
    finally:
        if driver.owned is not None:
            proof = supervisor.terminate_tree(driver.owned)
            facts["owned_process_stop_verified"] = proof["verified"]
        driver.detach_transport()
    return facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-input", action="store_true")
    args = parser.parse_args()
    scratch = ROOT / ".tmp" / ("receiver-evidence-native-" + uuid.uuid4().hex)
    try:
        result = probe(args.codex_bin, scratch, observe_input=args.observe_input)
    except Exception as error:  # noqa: BLE001 - never export process environment or credentials.
        result = {"status": "failed", "evidence_class": "installed_native_protocol_no_model",
                  "error_type": type(error).__name__, "scratch": str(scratch), "model_turns_requested": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(args.out)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
