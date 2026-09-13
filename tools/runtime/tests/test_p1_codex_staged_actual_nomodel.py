"""Boot the reviewed native binary from the scene's generated config, with no model turn."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from tools.runtime.p1_codex_host_scene import (
    _copy_pinned_native,
    _private_run_root,
    postflight_run,
)
from tools.runtime.p1_codex_lifecycle import DECISION_ID, stage_codex_home

NATIVE_SHA256 = "f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c"
NATIVE_SIZE = 258_597_984


@pytest.mark.skipif(sys.platform != "linux", reason="private catalog requires Linux")
def test_catalog_copy_is_digest_pinned_private_and_tool_free():
    from tools.runtime.tests.test_p1_codex_lifecycle import scene_profile

    if os.geteuid() == 0:
        pytest.skip("non-root owner path required")
    run_id = "p1-run-" + uuid.uuid4().hex
    root = _private_run_root(run_id)
    try:
        native = root / "bin" / "codex"
        native.write_bytes(b"x" * 1_000_000)
        native.chmod(0o500)
        catalog = root / "home" / "reviewed-models.json"
        catalog.write_text(
            json.dumps({"models": [{
                "slug": "gpt-5.6-sol",
                "experimental_supported_tools": [],
                "supported_reasoning_levels": [{"effort": "low"}],
                "display_name": "Fixture",
                "description": "fixture" * 200,
            }]}),
            encoding="utf-8",
        )
        catalog.chmod(0o600)
        scene = scene_profile()
        scene.update({
            "native_executable_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            "model_catalog_path": str(catalog),
            "model_catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            "model_catalog_size": catalog.stat().st_size,
        })
        staged = stage_codex_home(root, scene)
        assert Path(staged["catalog"]).read_bytes() == catalog.read_bytes()
        assert Path(staged["catalog"]).stat().st_mode & 0o777 == 0o600
        catalog.write_text(catalog.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with pytest.raises(ValueError, match="catalog digest"):
            stage_codex_home(root, scene)
        catalog.unlink()
        catalog.symlink_to(Path(staged["catalog"]))
        with pytest.raises(ValueError, match="profile file"):
            stage_codex_home(root, scene)
    finally:
        resolved = root.resolve(strict=True)
        assert resolved.parent == Path(f"/run/user/{os.geteuid()}/acs-p1-codex").resolve(
            strict=True
        )
        shutil.rmtree(resolved)


@pytest.mark.skipif(sys.platform != "linux", reason="reviewed native binary requires Linux")
def test_generated_scene_config_starts_actual_native_without_turn():
    if os.geteuid() == 0:
        pytest.skip("non-root user manager required")
    source = Path(os.getenv("ACS_P1_CODEX_NATIVE_PATH", ""))
    catalog_source = Path(os.getenv("ACS_P1_CODEX_CATALOG_PATH", ""))
    if not source.is_file() or not catalog_source.is_file():
        pytest.skip("reviewed native binary/catalog paths unavailable")
    run_id = "p1-run-" + uuid.uuid4().hex
    root = _private_run_root(run_id)
    supervisor = None
    try:
        native = root / "bin" / "codex"
        _copy_pinned_native(source, native, NATIVE_SHA256, NATIVE_SIZE)
        key_path = str(root / "home" / "missing-no-model-key")
        scene = {
            "schema_version": "acs-p1-codex-scene/1",
            "native_executable_path": str(source),
            "native_executable_sha256": NATIVE_SHA256,
            "native_executable_size": NATIVE_SIZE,
            "codex_version": "0.153.2",
            "schema_sha256": hashlib.sha256(
                (Path(__file__).parents[3] / "runtime_tests/schema-0.153.2/"
                 "codex_app_server_protocol.schemas.json").read_bytes()
            ).hexdigest(),
            "provider_alias": "fixture-provider",
            "provider_url": "https://provider.example.invalid/v1",
            "wire_api": "responses",
            "auth_command": "/usr/bin/cat",
            "auth_key_ref_path": key_path,
            "auth_key_ref_path_sha256": hashlib.sha256(key_path.encode()).hexdigest(),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "low",
            "model_catalog_entry": {
                "slug": "gpt-5.6-sol", "experimental_supported_tools": [],
            },
            "model_catalog_path": str(catalog_source),
            "model_catalog_sha256": hashlib.sha256(catalog_source.read_bytes()).hexdigest(),
            "model_catalog_size": catalog_source.stat().st_size,
            "max_turn_starts": 1,
            "max_collect_reads": 6,
            "max_elapsed_seconds": 120,
            "budget_evidence_ref": DECISION_ID,
        }
        staged = stage_codex_home(root, scene)
        schema = Path(__file__).parents[3] / (
            "runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json"
        )
        binding = BindingIdentity(
            "fixture-node", "fixture-boot", "fixture-runtime", "fixture-execution", "local-slot", 1
        )
        profile = LaunchProfile(
            staged["executable"], NATIVE_SHA256, "0.153.2", str(schema), scene["schema_sha256"],
            staged["cwd"], str(root / "codex-home"),
            hashlib.sha256(Path(staged["config"]).read_bytes()).hexdigest(),
            "achp-engineer",
            {
                "PATH": "/opt/acs/codex-sandbox/bin:/usr/bin:/bin",
                "HOME": staged["home"], "TMPDIR": staged["tmp"], "LANG": "C.UTF-8",
            },
            "gpt-5.6-sol",
        )
        supervisor = SystemdUserSupervisor(
            tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
            termination_timeout=10, environment_directory=root / "systemd-env",
        )
        driver = CodexAppServerDriver(
            run_id + "-binding", profile, DriverJournal(root / "ledger" / "driver.sqlite"),
            identity=binding, check_current=lambda _operation, observed: observed == binding
            or pytest.fail("binding changed"), supervisor=supervisor, rpc_timeout=15,
        )
        operation = AuthorizedOperation(
            run_id + "-spawn", run_id + "-command", run_id + "-message", "fixture-grant",
            datetime.now(UTC) + timedelta(seconds=90),
        )
        receipt = driver.spawn(operation)
        assert receipt["thread_id"] and receipt["session_id"]
        with driver.journal._connect() as connection:
            assert connection.execute(
                "SELECT count(*) FROM driver_events WHERE kind='rpc_dispatch' "
                "AND body LIKE '%turn/start%'"
            ).fetchone() == (0,)
        proof = supervisor.terminate_tree(driver.owned)
        assert proof["verified"] is True and proof["remaining_pids"] == []
        assert list((root / "systemd-env").iterdir()) == []
        observed = postflight_run(root, run_id)
        assert observed["remaining_pids"] == [] and observed["environment_files_remaining"] == 0
    finally:
        if supervisor is not None:
            supervisor.close()
        resolved = root.resolve(strict=True)
        assert resolved.parent == Path(f"/run/user/{os.geteuid()}/acs-p1-codex").resolve(
            strict=True
        )
        shutil.rmtree(resolved)
