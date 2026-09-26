"""Stage an exact-version Codex receiver factory without handling credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from runtime.receiver_deployment import inspect_factory

FACTORY_REFERENCE = "runtime_deployment.receiver_codex:callbacks"
FACTORY_SCHEMA = "acs-receiver-codex-factory/1"
REVIEWED_FACTORY_PROFILES = {
    "0.155.0": {"platform": "posix", "permission_profile": "achp-engineer"},
    "0.155.0-alpha.2.6": {"platform": "windows", "permission_profile": ":workspace"},
}
WINDOWS_HELPERS = (
    "codex-code-mode-host.exe",
    "codex-command-runner.exe",
    "codex-windows-sandbox-setup.exe",
)
VERSION_OUTPUT = re.compile(r"\Acodex-cli (0\.155\.0(?:-alpha\.2\.6)?)\Z")
IDENTITY = re.compile(r"\A[a-f0-9]{40}\Z")
ALIAS = re.compile(r"\A[a-z][a-z0-9_-]{1,63}\Z")


class FactoryStageRejected(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _platform() -> str:
    return "windows" if os.name == "nt" else "posix"


def _bounded_text(value: str, name: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise FactoryStageRejected(f"{name} is not bounded text")
    return value


def _absolute(path: str | Path, name: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or ".." in value.parts:
        raise FactoryStageRejected(f"{name} must be an absolute bounded path")
    return value


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = subprocess.run(
            ["whoami.exe"], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["icacls.exe", str(path), "/grant:r", f"{user}:(OI)(CI)F", "/T", "/C"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    else:
        path.chmod(0o700)


def _private_file(path: Path) -> None:
    if os.name == "nt":
        user = subprocess.run(
            ["whoami.exe"], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["icacls.exe", str(path), "/grant:r", f"{user}:F"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    else:
        path.chmod(0o600)


def _write_private(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FactoryStageRejected(f"refusing to replace staged file: {path.name}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(content)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("staged file write made no progress")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _private_file(path)


def _write_json_private(path: Path, value: object) -> None:
    _write_private(
        path,
        (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode(),
    )


def _command_environment(executable: Path, root: Path) -> dict[str, str]:
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        return {
            "PATH": str(executable.parent) + os.pathsep + system_root + r"\System32",
            "SystemRoot": system_root,
            "HOME": str(root / "home"),
            "TMP": str(root / "tmp"),
            "TEMP": str(root / "tmp"),
            "CODEX_HOME": str(root / "codex-home"),
        }
    return {
        "PATH": str(executable.parent) + ":/usr/bin:/bin",
        "HOME": str(root / "home"),
        "TMPDIR": str(root / "tmp"),
        "LANG": "C.UTF-8",
        "CODEX_HOME": str(root / "codex-home"),
    }


def detect_codex_version(executable: str | Path, *, host_platform: str | None = None) -> str:
    """Return only an exact reviewed version from the pinned executable."""
    native = _absolute(executable, "Codex executable")
    if not native.is_file():
        raise FactoryStageRejected("Codex executable is unavailable")
    observed = subprocess.run(
        [str(native), "--version"],
        env=_command_environment(native, native.parent),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    output = observed.stdout.strip()
    if len(output) > 128 or observed.stderr.strip():
        raise FactoryStageRejected("Codex version output differs from the reviewed shape")
    match = VERSION_OUTPUT.fullmatch(output)
    if match is None or match.group(1) not in REVIEWED_FACTORY_PROFILES:
        raise FactoryStageRejected("Codex version has no exact reviewed P2 factory profile")
    version = match.group(1)
    platform_name = host_platform or _platform()
    if REVIEWED_FACTORY_PROFILES[version]["platform"] != platform_name:
        raise FactoryStageRejected("Codex version is not reviewed for this host platform")
    return version


def _validate_catalog(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
        raise FactoryStageRejected("model catalog source is unavailable or unbounded")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise FactoryStageRejected("model catalog is not bounded JSON") from error

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if re.search(
                    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)",
                    str(key),
                ):
                    raise FactoryStageRejected("model catalog contains a credential-like field")
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)


def _validate_provider(
    *,
    platform_name: str,
    provider_alias: str,
    provider_name: str,
    provider_url: str,
    wire_api: str,
    auth_command: str,
    auth_reference: str,
) -> None:
    if not ALIAS.fullmatch(provider_alias):
        raise FactoryStageRejected("provider alias is invalid")
    if platform_name == "posix" and provider_alias != "zeo-dev":
        raise FactoryStageRejected("Linux P2 factory requires the reviewed zeo-dev provider alias")
    _bounded_text(provider_name, "provider name", 256)
    _bounded_text(auth_command, "provider auth command")
    _bounded_text(auth_reference, "provider auth reference")
    parsed = urlsplit(_bounded_text(provider_url, "provider URL", 2048))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or wire_api != "responses"
    ):
        raise FactoryStageRejected("provider route differs from the reviewed bounded shape")
    if platform_name == "posix":
        if (
            auth_command != "/usr/bin/cat"
            or not _absolute(auth_reference, "auth reference").is_absolute()
        ):
            raise FactoryStageRejected("Linux auth must be the reviewed command/path reference")
    elif not Path(auth_command).is_absolute():
        raise FactoryStageRejected("Windows provider auth command must be absolute")


def _config_text(
    *,
    root: Path,
    catalog: Path,
    permission_profile: str,
    model: str,
    provider_alias: str,
    provider_name: str,
    provider_url: str,
    wire_api: str,
    auth_command: str,
    auth_reference: str,
    platform_name: str,
) -> str:
    quote = json.dumps
    rows = [
        f"model = {quote(model)}",
        'model_reasoning_effort = "low"',
        f"model_provider = {quote(provider_alias)}",
        f"model_catalog_json = {quote(str(catalog))}",
        'approval_policy = "never"',
        f"default_permissions = {quote(permission_profile)}",
        "allow_login_shell = false",
        'web_search = "disabled"',
        "",
        "[features]",
        "multi_agent = false",
        "multi_agent_v2 = false",
        "shell_tool = false",
        "request_permissions_tool = false",
        "apps = false",
        "plugins = false",
        "recommended_plugins = false",
    ]
    if platform_name == "windows":
        rows.extend(("", "[windows]", 'sandbox = "unelevated"'))
    rows.extend(("", "[shell_environment_policy]", 'inherit = "none"'))
    if permission_profile == "achp-engineer":
        rows.extend(
            (
                "",
                "[permissions.achp-engineer.filesystem]",
                '":minimal" = "read"',
                f'{quote(str(root / "cwd"))} = "read"',
            )
        )
    rows.extend(
        (
            "",
            f"[model_providers.{provider_alias}]",
            f"name = {quote(provider_name)}",
            f"base_url = {quote(provider_url)}",
            f"wire_api = {quote(wire_api)}",
            "",
            f"[model_providers.{provider_alias}.auth]",
            f"command = {quote(auth_command)}",
            f"args = [{quote(auth_reference)}]",
            "timeout_ms = 5000",
            "refresh_interval_ms = 0",
            "",
        )
    )
    return "\n".join(rows)


def stage_factory(
    *,
    root: Path,
    executable: Path,
    catalog_source: Path,
    runtime_id: str,
    source_commit: str,
    source_tree: str,
    model: str,
    provider_alias: str,
    provider_name: str,
    provider_url: str,
    wire_api: str,
    auth_command: str,
    auth_reference: str,
) -> dict[str, Any]:
    """Create a factory binding from public references and pinned non-secret files."""
    root = _absolute(root, "factory root")
    executable = _absolute(executable, "Codex executable")
    catalog_source = _absolute(catalog_source, "model catalog")
    if root.exists() and any(root.iterdir()):
        raise FactoryStageRejected("factory root must be absent or empty")
    for directory in (
        root,
        root / "bin",
        root / "codex-home",
        root / "cwd",
        root / "home",
        root / "tmp",
        root / "artifacts",
        root / "state",
        root / "schema",
        root / "systemd-env",
        root / "state" / "windows-job",
    ):
        _private_directory(directory)
    platform_name = _platform()
    version = detect_codex_version(executable, host_platform=platform_name)
    profile = REVIEWED_FACTORY_PROFILES[version]
    if not IDENTITY.fullmatch(source_commit) or not IDENTITY.fullmatch(source_tree):
        raise FactoryStageRejected("source commit/tree identity is invalid")
    _bounded_text(runtime_id, "runtime id", 256)
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,127}", _bounded_text(model, "model", 128)):
        raise FactoryStageRejected("model identity is invalid")
    _validate_provider(
        platform_name=platform_name,
        provider_alias=provider_alias,
        provider_name=provider_name,
        provider_url=provider_url,
        wire_api=wire_api,
        auth_command=auth_command,
        auth_reference=auth_reference,
    )
    _validate_catalog(catalog_source)

    staged_executable = executable
    if platform_name == "windows":
        staged_executable = root / "bin" / "codex.exe"
        shutil.copyfile(executable, staged_executable)
        _private_file(staged_executable)
        for name in WINDOWS_HELPERS:
            helper = executable.parent / name
            if not helper.is_file():
                raise FactoryStageRejected("reviewed Windows Codex helper is missing: " + name)
            target = root / "bin" / name
            shutil.copyfile(helper, target)
            _private_file(target)
    executable_sha256 = _sha256(staged_executable)

    catalog = root / "codex-home" / "models.json"
    shutil.copyfile(catalog_source, catalog)
    _private_file(catalog)
    catalog_sha256 = _sha256(catalog)
    config = root / "codex-home" / "config.toml"
    _write_private(
        config,
        _config_text(
            root=root,
            catalog=catalog,
            permission_profile=profile["permission_profile"],
            model=model,
            provider_alias=provider_alias,
            provider_name=provider_name,
            provider_url=provider_url,
            wire_api=wire_api,
            auth_command=auth_command,
            auth_reference=auth_reference,
            platform_name=platform_name,
        ).encode(),
    )

    subprocess.run(
        [
            str(staged_executable),
            "app-server",
            "generate-json-schema",
            "--out",
            str(root / "schema"),
        ],
        env=_command_environment(staged_executable, root),
        capture_output=True,
        check=True,
        timeout=120,
    )
    protocol_schema = root / "schema" / "codex_app_server_protocol.schemas.json"
    if not protocol_schema.is_file() or protocol_schema.is_symlink():
        raise FactoryStageRejected("Codex did not generate the reviewed protocol schema artifact")
    try:
        schema_value = json.loads(protocol_schema.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise FactoryStageRejected("generated Codex protocol schema is malformed") from error
    if (
        not isinstance(schema_value, dict)
        or schema_value.get("$schema") != "http://json-schema.org/draft-07/schema#"
        or not isinstance(schema_value.get("definitions"), dict)
    ):
        raise FactoryStageRejected("generated Codex protocol schema identity differs")
    for generated in (root / "schema").rglob("*"):
        if generated.is_file():
            _private_file(generated)

    settings = {
        "schema_version": FACTORY_SCHEMA,
        "binding_id": "p2-codex-" + platform_name,
        "capacity_attempt_id": "p2-codex-capacity-" + platform_name,
        "executable": str(staged_executable),
        "executable_sha256": executable_sha256,
        "codex_version": version,
        "protocol_schema": str(protocol_schema),
        "protocol_schema_sha256": _sha256(protocol_schema),
        "model_catalog": str(catalog),
        "model_catalog_sha256": catalog_sha256,
        "cwd": str(root / "cwd"),
        "codex_home": str(root / "codex-home"),
        "config_sha256": _sha256(config),
        "permission_profile": profile["permission_profile"],
        "model": model,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "driver_journal": str(root / "state" / "driver.sqlite"),
        "node_journal": str(root / "state" / "node.sqlite"),
        "systemd_environment_dir": str(
            root / ("state/windows-job" if platform_name == "windows" else "systemd-env")
        ),
        "artifact_root": str(root / "artifacts"),
        "runtime_id": runtime_id,
        "spawn_operation_id": "p2-" + platform_name + "-spawn",
        "spawn_command_id": "p2-" + platform_name + "-spawn-command",
        "spawn_message_id": "p2-" + platform_name + "-spawn-message",
        "close_operation_id": "p2-" + platform_name + "-close",
        "close_command_id": "p2-" + platform_name + "-close-command",
        "close_message_id": "p2-" + platform_name + "-close-message",
        "collector_max_reads": 120,
        "collector_interval_seconds": 0.5,
    }
    settings_path = root / "factory-settings.json"
    _write_json_private(settings_path, settings)
    binding, _, _, _ = inspect_factory(FACTORY_REFERENCE, settings=settings)
    binding_path = root / "factory-binding.json"
    _write_json_private(binding_path, binding.model_dump(mode="json"))
    return {
        "version": version,
        "settings": settings,
        "settings_path": str(settings_path),
        "binding_path": str(binding_path),
        "factory_binding_sha256": _sha256(binding_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider-alias", required=True)
    parser.add_argument("--provider-name", required=True)
    parser.add_argument("--provider-url", required=True)
    parser.add_argument("--wire-api", choices=("responses",), required=True)
    parser.add_argument("--auth-command", required=True)
    parser.add_argument("--auth-reference", required=True)
    arguments = parser.parse_args(argv)
    staged = stage_factory(
        root=arguments.root,
        executable=arguments.executable,
        catalog_source=arguments.catalog,
        runtime_id=arguments.runtime_id,
        source_commit=arguments.source_commit,
        source_tree=arguments.source_tree,
        model=arguments.model,
        provider_alias=arguments.provider_alias,
        provider_name=arguments.provider_name,
        provider_url=arguments.provider_url,
        wire_api=arguments.wire_api,
        auth_command=arguments.auth_command,
        auth_reference=arguments.auth_reference,
    )
    print(
        json.dumps(
            {key: value for key, value in staged.items() if key != "settings"}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
