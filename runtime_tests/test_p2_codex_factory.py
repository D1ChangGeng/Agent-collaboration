"""Exact Codex P2 factory admission and no-secret staging checks."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.codex_driver import DriverRejected, LaunchProfile
from runtime_deployment.receiver_codex import validate_settings
from tools.runtime.p2_codex_factory import (
    FactoryStageRejected,
    detect_codex_version,
    stage_factory,
)

ROOT = Path(__file__).parents[1]
LINUX_CODEX = Path("/home/changgeng/.nvm/versions/node/v24.11.1/bin/codex")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_codex(path: Path, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"VERSION = {version!r}\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli ' + VERSION)\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:3] == ['app-server', 'generate-json-schema'] and sys.argv[3] == '--out':\n"
        "    out = pathlib.Path(sys.argv[4]); out.mkdir(parents=True, exist_ok=True)\n"
        "    (out / 'codex_app_server_protocol.schemas.json').write_text(json.dumps({\n"
        "        '$schema': 'http://json-schema.org/draft-07/schema#', 'definitions': {}\n"
        "    }))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _catalog(path: Path) -> None:
    path.write_text(
        json.dumps({"models": [{"slug": "gpt-5.6-sol", "experimental_supported_tools": []}]}),
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_exact_driver_profile_admission_and_workspace_boundary(tmp_path):
    executable = tmp_path / "codex"
    schema = tmp_path / "schema.json"
    home = tmp_path / "codex-home"
    cwd = tmp_path / "cwd"
    executable.write_bytes(b"codex")
    schema.write_bytes(b"schema")
    home.mkdir()
    cwd.mkdir()
    (home / "config.toml").write_text(
        'approval_policy = "never"\ndefault_permissions = "achp-engineer"\n',
        encoding="utf-8",
    )
    common = {
        "executable": str(executable),
        "executable_sha256": _sha(executable),
        "schema_path": str(schema),
        "schema_sha256": _sha(schema),
        "cwd": str(cwd),
        "codex_home": str(home),
        "config_sha256": _sha(home / "config.toml"),
        "environment": {},
    }
    LaunchProfile(version="0.155.0", permission_profile="achp-engineer", **common).validate()
    (home / "config.toml").write_text(
        'approval_policy = "never"\ndefault_permissions = ":workspace"\n',
        encoding="utf-8",
    )
    common["config_sha256"] = _sha(home / "config.toml")
    LaunchProfile(
        version="0.155.0-alpha.2.6",
        permission_profile=":workspace",
        **common,
    ).validate()
    with pytest.raises(DriverRejected):
        LaunchProfile(version="0.155", permission_profile="achp-engineer", **common).validate()
    with pytest.raises(DriverRejected):
        LaunchProfile(version="0.155.0", permission_profile=":workspace", **common).validate()


@pytest.mark.parametrize("version", ["0.155.0", "0.155.0-alpha.2.6", "0.155.0.1", "latest"])
def test_detect_codex_version_is_exact_and_platform_bound(tmp_path, monkeypatch, version):
    executable = tmp_path / "codex"
    executable.write_bytes(b"pinned-codex-binary")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            _args[0], 0, stdout=f"codex-cli {version}\n", stderr=""
        ),
    )
    if version == "0.155.0":
        assert detect_codex_version(executable, host_platform="posix") == version
    elif version == "0.155.0-alpha.2.6":
        assert detect_codex_version(executable, host_platform="windows") == version
    else:
        with pytest.raises(FactoryStageRejected):
            detect_codex_version(executable, host_platform="posix")


@pytest.mark.skipif(os.name != "posix", reason="fixture stages the reviewed POSIX factory")
def test_factory_stages_generated_schema_and_never_secret_values(tmp_path):
    import runtime_deployment
    import runtime_deployment.receiver_codex as deployment

    for source in (runtime_deployment.__file__, deployment.__file__):
        path = Path(source)
        path.chmod(path.stat().st_mode & ~0o022)
    executable = tmp_path / "codex"
    catalog = tmp_path / "catalog.json"
    _fake_codex(executable, "0.155.0")
    _catalog(catalog)
    root = tmp_path / "stage"
    staged = stage_factory(
        root=root,
        executable=executable,
        catalog_source=catalog,
        runtime_id="runtime-linux",
        source_commit="a" * 40,
        source_tree="b" * 40,
        model="gpt-5.6-sol",
        provider_alias="zeo-dev",
        provider_name="Reviewed ZEO",
        provider_url="https://provider.example.invalid/v1",
        wire_api="responses",
        auth_command="/usr/bin/cat",
        auth_reference=str(root / "auth-reference"),
    )
    settings = staged["settings"]
    assert settings["codex_version"] == "0.155.0"
    schema = Path(settings["protocol_schema"])
    assert _sha(schema) == settings["protocol_schema_sha256"]
    assert json.loads(schema.read_text())["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert Path(staged["settings_path"]).stat().st_mode & 0o777 == 0o600
    assert Path(staged["binding_path"]).stat().st_mode & 0o777 == 0o600
    for path in (
        Path(staged["settings_path"]),
        Path(staged["binding_path"]),
        root / "codex-home/config.toml",
    ):
        contents = path.read_text(encoding="utf-8")
        assert "api-key" not in contents.lower()
        assert "secret-value" not in contents
        assert "token-value" not in contents
    validate_settings(settings)


@pytest.mark.skipif(os.name != "posix", reason="fixture stages the reviewed POSIX factory")
def test_factory_rejects_credential_like_catalog_fields(tmp_path):
    executable = tmp_path / "codex"
    _fake_codex(executable, "0.155.0")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"api_key": "secret-value"}), encoding="utf-8")
    with pytest.raises(FactoryStageRejected, match="credential"):
        stage_factory(
            root=tmp_path / "stage",
            executable=executable,
            catalog_source=catalog,
            runtime_id="runtime-linux",
            source_commit="a" * 40,
            source_tree="b" * 40,
            model="gpt-5.6-sol",
            provider_alias="zeo-dev",
            provider_name="Reviewed ZEO",
            provider_url="https://provider.example.invalid/v1",
            wire_api="responses",
            auth_command="/usr/bin/cat",
            auth_reference=str(tmp_path / "auth-reference"),
        )


def test_actual_linux_codex_0155_no_model_app_server_bootstrap(tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0 or not LINUX_CODEX.is_file():
        pytest.skip("installed non-root Linux Codex 0.155.0 is unavailable")
    observed = subprocess.run(
        [str(LINUX_CODEX), "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert observed.stdout.strip() == "codex-cli 0.155.0" and not observed.stderr.strip()
    schema_dir = tmp_path / "schema"
    generated = subprocess.run(
        [str(LINUX_CODEX), "app-server", "generate-json-schema", "--out", str(schema_dir)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    schema = schema_dir / "codex_app_server_protocol.schemas.json"
    assert not generated.stderr and schema.is_file()
    assert json.loads(schema.read_text())["$schema"] == "http://json-schema.org/draft-07/schema#"
    home = tmp_path / "codex-home"
    home.mkdir(mode=0o700)
    cwd = tmp_path / "cwd"
    cwd.mkdir(mode=0o700)
    (home / "config.toml").write_text(
        'approval_policy = "never"\ndefault_permissions = "achp-engineer"\n'
        "[features]\nmulti_agent = false\nmulti_agent_v2 = false\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [str(LINUX_CODEX), "--disable", "multi_agent", "--disable", "multi_agent_v2", "app-server"],
        cwd=cwd,
        env={
            "PATH": str(LINUX_CODEX.parent),
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "CODEX_HOME": str(home),
            "LANG": "C.UTF-8",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin and process.stdout
    process.stdin.write(
        json.dumps(
            {
                "id": "initialize",
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "acs_runtime", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        + "\n"
    )
    process.stdin.flush()
    line = process.stdout.readline()
    assert line
    response = json.loads(line)
    assert response["id"] == "initialize"
    result = response["result"]
    assert "0.155.0" in result["userAgent"]
    assert Path(result["codexHome"]) == home
    process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
    process.stdin.flush()
    process.terminate()
    process.wait(timeout=10)
