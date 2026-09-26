"""P1 Gate evidence runner candidate.

The runner captures evidence for one local P1 profile.  It does not infer Gate
success from component test summaries and it never edits the formal Gate files.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PLAN_SCHEMA = "acs-p1-gate-runner-plan/1"
STATE_SCHEMA = "acs-p1-gate-runner-state/1"
PROBE_SCHEMA = "acs-p1-gate-probe-result/1"
MANIFEST_SCHEMA = "acs-p1-gate-run-manifest/1"
STATE_KEY_NAME = ".runner-state.key"
MACHINE_SCHEMA = "acs-machine-observation/1"
GATE_RECORD_SCHEMA = "acs-gate-record/1"
EVIDENCE_KINDS = frozenset(
    {"command_output", "postgresql", "sqlite", "temporal", "driver", "os"}
)
EVIDENCE_FIELDS = (
    "receipts",
    "raw_outputs",
    "fault_injection",
    "source_readback",
    "artifact_readback",
    "effect_readback",
    "recovery_trace",
)
READBACK_FLAGS = {
    "source_readback": "source_readback_verified",
    "artifact_readback": "artifact_readback_verified",
    "effect_readback": "effect_readback_verified",
    "recovery_trace": "recovery_verified",
}
ID_FIELDS = ("operation_ids", "message_ids", "event_ids")
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
SOURCE_GUARD_CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_GUARD_BYTES = 256 * 1024 * 1024
MAX_SOURCE_GUARD_ENTRIES = 1_000_000
MAX_RUNTIME_ENVIRONMENT_FILE_BYTES = 64 * 1024 * 1024
MAX_COMMANDS = 64
MAX_TIMEOUT_SECONDS = 3600
UNKNOWN = {"", "unknown", "unverified", "not_run", "not-measured", "tbd", "n/a"}
PLAN_KEYS = {
    "schema_version", "profile", "node_id", "engineer", "direction", "expires_at",
    "core_version", "temporal_version", "postgresql_version", "protocol_version",
    "credential_scope", "policy", "harness_versions", "driver_versions",
    "scenarios", "prerequisites", "review", "runtime_profile",
}
COMMAND_KEYS = {"command_id", "kind", "argv", "evidence_fields", "timeout_seconds", "cwd"}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+[^\s]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/@\s\"]+@", re.IGNORECASE),
    re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{16,}\b"),
)


class RunnerError(RuntimeError):
    pass


class PlanError(RunnerError):
    pass


class EvidenceError(RunnerError):
    pass


class SourceMutationError(EvidenceError):
    pass


class SandboxUnavailable(EvidenceError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: object) -> str:
    return digest_bytes(canonical(value))


def stamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (AttributeError, ValueError, OverflowError) as error:
        raise PlanError("timezone-aware timestamp required") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise PlanError("timezone-aware timestamp required")
    return result.astimezone(UTC)


def now_text() -> str:
    return datetime.now(UTC).isoformat()


def known_text(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() not in UNKNOWN


def strict_json(data: bytes) -> Any:
    if len(data) > MAX_OUTPUT_BYTES:
        raise EvidenceError("JSON exceeds runner bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise EvidenceError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise EvidenceError("nonfinite JSON")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("invalid JSON evidence") from error


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def write_json(path: Path, value: object) -> None:
    write_atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n")


def remove_private_stage(stage: Path) -> None:
    if not stage.exists():
        return
    for path in sorted(stage.rglob("*"), reverse=True):
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)
    stage.chmod(0o700)
    shutil.rmtree(stage)


def create_state_key(run_dir: Path) -> None:
    path = run_dir / STATE_KEY_NAME
    if path.exists():
        raise RunnerError("runner state key already exists")
    write_atomic(path, secrets.token_bytes(32))
    path.chmod(0o600)


def read_state_key(run_dir: Path) -> bytes:
    path = run_dir / STATE_KEY_NAME
    data = path.read_bytes()
    if len(data) != 32 or path.is_symlink():
        raise RunnerError("runner state key is invalid")
    if os.name == "posix":
        info = path.stat()
        if info.st_uid != os.geteuid() or (info.st_mode & 0o777) != 0o600:
            raise RunnerError("runner state key is not owner-only")
    return data


def state_mac(state: dict[str, Any], key: bytes) -> str:
    payload = {name: value for name, value in state.items() if name != "state_hmac"}
    return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()


def write_state(run_dir: Path, state: dict[str, Any]) -> None:
    key = read_state_key(run_dir)
    previous = state.get("state_hmac", "")
    state["previous_state_hmac"] = previous
    state["state_revision"] = int(state.get("state_revision", 0)) + 1
    state["state_hmac"] = state_mac(state, key)
    write_json(run_dir / "state.json", state)


def load_state(run_dir: Path) -> dict[str, Any]:
    state = strict_json((run_dir / "state.json").read_bytes())
    if not isinstance(state, dict) or not hmac.compare_digest(
        str(state.get("state_hmac", "")), state_mac(state, read_state_key(run_dir)),
    ):
        raise RunnerError("runner state HMAC verification failed")
    return state


def file_ref(path: Path, root: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(root.resolve(strict=True)).as_posix()
    return {"path": relative, "sha256": digest_bytes(resolved.read_bytes())}


def validate_ref(ref: object, root: Path) -> Path:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise EvidenceError("reference requires path and sha256")
    name, expected = ref["path"], ref["sha256"]
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
        raise EvidenceError("invalid evidence reference")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise EvidenceError("evidence reference escapes run")
    path = root / relative
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink():
            raise EvidenceError("symlink evidence rejected")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root.resolve(strict=True))
    if not resolved.is_file() or not 0 < resolved.stat().st_size <= MAX_OUTPUT_BYTES:
        raise EvidenceError("evidence file missing, empty or oversized")
    if digest_bytes(resolved.read_bytes()) != expected:
        raise EvidenceError("evidence digest mismatch")
    return resolved


def _secure_owner_file(path: Path, expected_sha256: str) -> bytes:
    if os.name != "posix":
        raise PlanError("runtime profile mounts require POSIX owner-only paths")
    if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise PlanError("runtime profile file reference is invalid")
    parent_fd = _owner_directory(path.parent)
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd,
        )
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise PlanError("runtime profile file must be owner 0600 single-link")
            data = b""
            while chunk := os.read(descriptor, 65536):
                data += chunk
                if len(data) > MAX_OUTPUT_BYTES:
                    raise PlanError("runtime profile JSON exceeds runner bound")
            after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino):
                raise PlanError("runtime profile file identity changed")
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)
    if digest_bytes(data) != expected_sha256:
        raise PlanError("runtime profile file digest mismatch")
    return data


def _owner_directory(path: Path) -> int:
    """Walk POSIX ancestors with NOFOLLOW and return an owner-private dirfd."""
    if os.name != "posix" or not path.is_absolute():
        raise PlanError("owner-private POSIX directory required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            info = os.fstat(next_fd)
            mode = stat.S_IMODE(info.st_mode)
            final = index == len(parts) - 1
            permitted_ancestor = (
                info.st_uid in {0, os.geteuid()}
                and (not mode & 0o022 or info.st_uid == 0 and mode & stat.S_ISVTX)
            )
            if (not stat.S_ISDIR(info.st_mode)
                    or final and (info.st_uid != os.geteuid() or mode != 0o700)
                    or not final and not permitted_ancestor):
                os.close(next_fd)
                raise PlanError("owner-private directory ancestor is invalid")
            os.close(descriptor)
            descriptor = next_fd
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _member_file(root_fd: int, name: str, expected: dict[str, Any]) -> None:
    parts = Path(name).parts
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            info = os.fstat(following)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                os.close(following)
                raise PlanError("runtime environment member directory is invalid")
            os.close(directory)
            directory = following
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory,
        )
        try:
            info = os.fstat(descriptor)
            value = hashlib.sha256()
            read_bytes = 0
            while chunk := os.read(descriptor, 65536):
                read_bytes += len(chunk)
                if read_bytes > MAX_RUNTIME_ENVIRONMENT_FILE_BYTES:
                    raise PlanError("runtime environment file exceeds runner bound")
                value.update(chunk)
            after = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != expected["mode"] or info.st_nlink != 1
                    or (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino)
                    or value.hexdigest() != expected["sha256"]):
                raise PlanError("runtime environment file verification failed")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


@contextmanager
def pinned_runtime_mounts(plan: dict[str, Any]):
    configured = plan.get("runtime_profile")
    if configured is None:
        yield {}, ()
        return
    validate_runtime_profile(configured)
    profile_path = Path(configured["profile_path"])
    root_path = Path(configured["runtime_environment_root"])
    bus_parent = Path(f"/run/user/{os.geteuid()}")
    descriptors: list[int] = []
    try:
        profile_parent_fd = _owner_directory(profile_path.parent)
        descriptors.append(profile_parent_fd)
        profile_fd = os.open(
            profile_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=profile_parent_fd,
        )
        descriptors.append(profile_fd)
        root_fd = _owner_directory(root_path)
        descriptors.append(root_fd)
        bus_parent_fd = _owner_directory(bus_parent)
        descriptors.append(bus_parent_fd)
        bus_info = os.stat("bus", dir_fd=bus_parent_fd, follow_symlinks=False)
        if not stat.S_ISSOCK(bus_info.st_mode) or bus_info.st_uid != os.geteuid():
            raise SandboxUnavailable("reviewed user bus is unavailable")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(2.0)
            peer.connect(f"/proc/self/fd/{bus_parent_fd}/bus")
            _pid, peer_uid, _gid = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
            )
            if peer_uid != os.geteuid():
                raise SandboxUnavailable("reviewed user bus peer changed")
        for path, descriptor in (
            (profile_path, profile_fd), (root_path, root_fd), (bus_parent, bus_parent_fd),
        ):
            actual = path.stat(follow_symlinks=False)
            held = os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino) != (held.st_dev, held.st_ino):
                raise SandboxUnavailable("runtime mount identity changed")
        sources = {
            "profile": f"/proc/self/fd/{profile_fd}",
            "environment": f"/proc/self/fd/{root_fd}",
            "bus": f"/proc/self/fd/{bus_parent_fd}/bus",
            "bus_identity": (bus_info.st_dev, bus_info.st_ino),
        }
        yield sources, tuple(descriptors)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def assert_runtime_mounts_unchanged(
    plan: dict[str, Any], sources: dict[str, Any], descriptors: tuple[int, ...],
) -> None:
    if plan.get("runtime_profile") is None:
        return
    configured = plan["runtime_profile"]
    profile_path = Path(configured["profile_path"])
    roots = (
        (profile_path.parent, descriptors[0]),
        (Path(configured["runtime_environment_root"]), descriptors[2]),
        (Path(f"/run/user/{os.geteuid()}"), descriptors[3]),
    )
    for path, held in roots:
        fresh = _owner_directory(path)
        try:
            if (os.fstat(fresh).st_dev, os.fstat(fresh).st_ino) != (
                os.fstat(held).st_dev, os.fstat(held).st_ino,
            ):
                raise SandboxUnavailable("runtime mount ancestor changed")
        finally:
            os.close(fresh)
    profile = os.stat(profile_path.name, dir_fd=descriptors[0], follow_symlinks=False)
    held_profile = os.fstat(descriptors[1])
    if (profile.st_dev, profile.st_ino) != (held_profile.st_dev, held_profile.st_ino):
        raise SandboxUnavailable("runtime profile file changed before mount")
    bus = os.stat("bus", dir_fd=descriptors[3], follow_symlinks=False)
    if (bus.st_dev, bus.st_ino) != tuple(sources["bus_identity"]):
        raise SandboxUnavailable("user bus socket changed before mount")


def validate_runtime_profile(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    keys = {
        "profile_path", "profile_sha256", "runtime_environment_root",
        "runtime_environment_manifest_sha256", "network_mode",
        "postgresql_endpoint", "temporal_endpoint",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise PlanError("runtime_profile fields are invalid")
    if value["network_mode"] != "host_loopback_providers":
        raise PlanError("runtime profile network mode is invalid")
    if (value["postgresql_endpoint"] != "127.0.0.1:54329"
            or value["temporal_endpoint"] != "127.0.0.1:7239"):
        raise PlanError("runtime profile endpoints must be reviewed loopback providers")
    profile_path = Path(value["profile_path"])
    profile = strict_json(_secure_owner_file(profile_path, value["profile_sha256"]))
    profile_keys = {
        "schema_version", "profile", "source_root", "python", "sandbox_python",
        "postgres_dsn", "temporal_endpoint", "temporal_namespace", "versions",
        "node_id", "direction", "codex_model_evidence", "opencode_model_evidence",
    }
    if (not isinstance(profile, dict) or set(profile) != profile_keys
            or profile.get("schema_version") != "acs-p1-loopback-probe-profile/1"):
        raise PlanError("runtime profile JSON schema is invalid")
    if (profile.get("profile") != "p1-loopback-provider"
            or not known_text(profile.get("source_root"))
            or not Path(profile["source_root"]).is_absolute()
            or not known_text(profile.get("python")) or not Path(profile["python"]).is_absolute()
            or profile.get("sandbox_python") != "/run/acs-p1/runtime/bin/python"
            or not known_text(profile.get("postgres_dsn"))
            or profile.get("temporal_endpoint") != value["temporal_endpoint"]
            or not known_text(profile.get("temporal_namespace"))
            or not isinstance(profile.get("versions"), dict)
            or not known_text(profile.get("node_id"))
            or not known_text(profile.get("direction"))):
        raise PlanError("runtime profile provider identity is invalid")
    try:
        dsn = urlsplit(profile["postgres_dsn"])
        if (dsn.scheme not in {"postgres", "postgresql"} or dsn.hostname != "127.0.0.1"
                or dsn.port != 54329):
            raise PlanError("runtime profile PostgreSQL DSN is not reviewed loopback")
    except ValueError as error:
        raise PlanError("runtime profile PostgreSQL DSN is invalid") from error
    root = Path(value["runtime_environment_root"])
    if not root.is_absolute() or root.is_symlink():
        raise PlanError("runtime environment root is invalid")
    root_fd = _owner_directory(root)
    try:
        manifest_path = root / "manifest.json"
        manifest = strict_json(_secure_owner_file(
            manifest_path, value["runtime_environment_manifest_sha256"],
        ))
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "files"}
                or manifest.get("schema_version") != "acs-p1-runtime-environment/1"
                or not isinstance(files, dict) or "bin/python" not in files):
            raise PlanError("runtime environment manifest is invalid")
        directories = [path for path in root.rglob("*") if path.is_dir()]
        if any(path.is_symlink() or path.stat().st_uid != os.geteuid()
               or stat.S_IMODE(path.stat().st_mode) != 0o700 for path in directories):
            raise PlanError("runtime environment directory verification failed")
        actual = {
            path.relative_to(root).as_posix() for path in root.rglob("*")
            if path.is_file() and path != manifest_path
        }
        if actual != set(files) or any(
            Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name
            or any(not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9._-]{0,127}", part)
                   for part in Path(name).parts)
            for name in files
        ):
            raise PlanError("runtime environment contains extra or missing files")
        for name, expected in files.items():
            if (not isinstance(expected, dict) or set(expected) != {"sha256", "mode"}
                    or expected["mode"] not in {0o600, 0o700}):
                raise PlanError("runtime environment file manifest is invalid")
            _member_file(root_fd, name, expected)
    finally:
        os.close(root_fd)
    return {
        "profile_sha256": value["profile_sha256"],
        "runtime_environment_manifest_sha256": value[
            "runtime_environment_manifest_sha256"
        ],
        "network_mode": value["network_mode"],
        "postgresql_endpoint": value["postgresql_endpoint"],
        "temporal_endpoint": value["temporal_endpoint"],
        "profile": profile["profile"],
        "node_id": profile["node_id"],
        "direction": profile["direction"],
        "versions_sha256": digest(profile["versions"]),
        "plan_versions_sha256": digest({
            "core": profile["versions"].get("core"),
            "provider": {"temporal": profile["versions"].get("provider", {}).get("temporal")},
            "database": {
                "postgresql": profile["versions"].get("database", {}).get("postgresql")
            },
            "protocol": profile["versions"].get("protocol"),
            "harness": profile["versions"].get("harness"),
            "driver": profile["versions"].get("driver"),
        }),
        "source_root_sha256": digest(str(Path(profile["source_root"]).resolve(strict=True))),
    }


def secret_findings(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="replace")
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def redacted(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text.encode()


@dataclass(frozen=True)
class SourceIdentity:
    commit: str
    tree: str


def git_value(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args], capture_output=True, text=True, timeout=30,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise RunnerError("Git source identity unavailable")
    return result.stdout.strip()


def source_identity(source_root: Path) -> SourceIdentity:
    commit = git_value(source_root, "rev-parse", "HEAD")
    tree = git_value(source_root, "rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise RunnerError("full Git commit and tree required")
    if git_value_allow_empty(source_root, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("tracked source worktree must be clean")
    return SourceIdentity(commit, tree)


def git_value_allow_empty(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args], capture_output=True, text=True, timeout=30,
        check=False,
    )
    if result.returncode:
        raise RunnerError("Git source state unavailable")
    return result.stdout.strip()


def git_bytes(source_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args], capture_output=True, timeout=60,
        check=False,
    )
    if result.returncode:
        raise RunnerError("Git source inventory unavailable")
    return result.stdout


def listed_paths(source_root: Path, *args: str) -> set[str]:
    return {
        value.decode("utf-8", errors="surrogateescape")
        for value in git_bytes(source_root, *args).split(b"\0") if value
    }


def sensitive_ignored(name: str) -> bool:
    lowered = name.lower()
    parts = Path(name).parts
    return (
        bool(parts and parts[0] == "gates")
        or any(part in {".env", ".secrets", "secrets", "credentials"} for part in parts)
        or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
        or "secret" in lowered
    )


def inventory_entry(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    identity = {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "uid": getattr(info, "st_uid", None),
        "gid": getattr(info, "st_gid", None),
        "size": info.st_size,
    }
    if path.is_symlink():
        return {**identity, "kind": "symlink", "target": os.readlink(path)}
    if path.is_file():
        return {**identity, "kind": "file", "sha256": digest_bytes(path.read_bytes())}
    if path.is_dir():
        return {**identity, "kind": "directory"}
    return {**identity, "kind": "other"}


def collect_source_guard(source_root: Path) -> dict[str, Any]:
    tracked = listed_paths(source_root, "ls-files", "-z", "--cached")
    untracked = listed_paths(source_root, "ls-files", "-z", "--others", "--exclude-standard")
    ignored = {
        name for name in listed_paths(
            source_root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
        ) if sensitive_ignored(name)
    }
    gates_root = source_root / "gates"
    protected = {"gates"}
    if gates_root.is_dir() and not gates_root.is_symlink():
        protected.update(
            path.relative_to(source_root).as_posix()
            for path in gates_root.rglob("*")
        )
    names = sorted(tracked | untracked | ignored | protected)
    entries = {name: inventory_entry(source_root / name) for name in names}
    status = git_bytes(
        source_root, "status", "--porcelain=v2", "--untracked-files=all", "--ignored=matching",
    )
    git_dir = Path(git_value(source_root, "rev-parse", "--absolute-git-dir"))
    index_full = inventory_entry(git_dir / "index")
    index = {
        key: index_full.get(key)
        for key in ("kind", "mode", "size", "sha256")
    }
    result = {
        "schema_version": "acs-p1-source-guard/1",
        "head": git_value(source_root, "rev-parse", "HEAD"),
        "tree": git_value(source_root, "rev-parse", "HEAD^{tree}"),
        "index": index,
        "status_sha256": digest_bytes(status),
        "tracked": sorted(tracked),
        "untracked": sorted(untracked),
        "ignored_sensitive": sorted(ignored),
        "protected": sorted(protected),
        "entries": entries,
    }
    return {**result, "inventory_sha256": digest(result)}


def persist_source_guard(run_dir: Path, guard: dict[str, Any]) -> dict[str, Any]:
    """Store the complete source inventory outside the bounded HMAC state."""
    categories = ("tracked", "untracked", "ignored_sensitive", "protected")
    members = {name: set(guard[name]) for name in categories}
    records = [
        {
            "path": name,
            "categories": [category for category in categories if name in members[category]],
            "entry": guard["entries"][name],
        }
        for name in sorted(guard["entries"])
    ]
    if len(records) > MAX_SOURCE_GUARD_ENTRIES:
        raise RunnerError("source guard entry count exceeds runner bound")
    directory = run_dir / "source-guard"
    directory.mkdir(parents=True)
    chunks: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    total_bytes = 0

    def flush() -> None:
        nonlocal batch, total_bytes
        if not batch:
            return
        payload = canonical({"schema_version": "acs-p1-source-guard-chunk/1", "entries": batch})
        if len(payload) > SOURCE_GUARD_CHUNK_BYTES:
            raise RunnerError("source guard entry exceeds chunk bound")
        total_bytes += len(payload)
        if total_bytes > MAX_SOURCE_GUARD_BYTES:
            raise RunnerError("source guard exceeds runner bound")
        path = directory / f"chunk-{len(chunks):06d}.json"
        write_atomic(path, payload + b"\n")
        chunks.append({
            **file_ref(path, run_dir),
            "count": len(batch),
            "first": batch[0]["path"],
            "last": batch[-1]["path"],
        })
        batch = []

    for record in records:
        candidate = [*batch, record]
        if batch and len(canonical({
            "schema_version": "acs-p1-source-guard-chunk/1", "entries": candidate,
        })) > SOURCE_GUARD_CHUNK_BYTES:
            flush()
        batch.append(record)
    flush()
    category_digests = {name: digest(guard[name]) for name in categories}
    manifest = {
        "schema_version": "acs-p1-source-guard-manifest/1",
        "head": guard["head"],
        "tree": guard["tree"],
        "index": guard["index"],
        "status_sha256": guard["status_sha256"],
        "inventory_sha256": guard["inventory_sha256"],
        "entry_count": len(records),
        "category_counts": {name: len(guard[name]) for name in categories},
        "category_digests": category_digests,
        "chunk_count": len(chunks),
        "canonical_chunk_bytes": total_bytes,
        "chunks": chunks,
    }
    manifest_path = directory / "manifest.json"
    write_json(manifest_path, manifest)
    return {
        "manifest": file_ref(manifest_path, run_dir),
        "inventory_sha256": guard["inventory_sha256"],
        "entry_count": len(records),
        "category_counts": manifest["category_counts"],
    }


def load_source_guard(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    summary = state.get("source_guard")
    if not isinstance(summary, dict) or set(summary) != {
        "manifest", "inventory_sha256", "entry_count", "category_counts",
    }:
        raise EvidenceError("source guard state summary is invalid")
    manifest = strict_json(validate_ref(summary["manifest"], run_dir).read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema_version") != (
        "acs-p1-source-guard-manifest/1"
    ):
        raise EvidenceError("source guard manifest is invalid")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != manifest.get("chunk_count"):
        raise EvidenceError("source guard chunk manifest is invalid")
    categories = ("tracked", "untracked", "ignored_sensitive", "protected")
    paths = {name: [] for name in categories}
    entries: dict[str, Any] = {}
    total_bytes = 0
    previous = None
    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != {
            "path", "sha256", "count", "first", "last",
        }:
            raise EvidenceError("source guard chunk reference is invalid")
        raw = validate_ref({key: chunk[key] for key in ("path", "sha256")}, run_dir).read_bytes()
        total_bytes += len(raw.rstrip(b"\n"))
        if total_bytes > MAX_SOURCE_GUARD_BYTES:
            raise EvidenceError("source guard exceeds runner bound")
        payload = strict_json(raw)
        values = payload.get("entries") if isinstance(payload, dict) else None
        if (payload.get("schema_version") != "acs-p1-source-guard-chunk/1"
                or not isinstance(values, list) or len(values) != chunk["count"]
                or not values or values[0].get("path") != chunk["first"]
                or values[-1].get("path") != chunk["last"]):
            raise EvidenceError("source guard chunk identity is invalid")
        for record in values:
            if not isinstance(record, dict) or set(record) != {"path", "categories", "entry"}:
                raise EvidenceError("source guard record is invalid")
            name = record["path"]
            kinds = record["categories"]
            if (not isinstance(name, str) or not isinstance(kinds, list)
                    or any(kind not in categories for kind in kinds)
                    or len(kinds) != len(set(kinds)) or name in entries
                    or previous is not None and name <= previous):
                raise EvidenceError("source guard ordering or category is invalid")
            previous = name
            entries[name] = record["entry"]
            for kind in kinds:
                paths[kind].append(name)
    if (len(entries) != manifest.get("entry_count")
            or len(entries) != summary.get("entry_count")
            or total_bytes != manifest.get("canonical_chunk_bytes")):
        raise EvidenceError("source guard count is invalid")
    if ({name: len(paths[name]) for name in categories} != manifest.get("category_counts")
            or manifest.get("category_counts") != summary.get("category_counts")
            or {name: digest(paths[name]) for name in categories}
            != manifest.get("category_digests")):
        raise EvidenceError("source guard category manifest is invalid")
    result = {
        "schema_version": "acs-p1-source-guard/1",
        "head": manifest.get("head"),
        "tree": manifest.get("tree"),
        "index": manifest.get("index"),
        "status_sha256": manifest.get("status_sha256"),
        **paths,
        "entries": entries,
    }
    expected = digest(result)
    if (expected != manifest.get("inventory_sha256")
            or expected != summary.get("inventory_sha256")):
        raise EvidenceError("source guard inventory digest mismatch")
    return {**result, "inventory_sha256": expected}


def source_guard_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    names = set(before.get("entries", {})) | set(after.get("entries", {}))
    changed = sorted(
        name for name in names
        if before.get("entries", {}).get(name) != after.get("entries", {}).get(name)
    )
    metadata = [
        field for field in ("head", "tree", "index", "status_sha256", "tracked", "untracked", "ignored_sensitive", "protected")
        if before.get(field) != after.get(field)
    ]
    return {
        "before_sha256": before.get("inventory_sha256"),
        "after_sha256": after.get("inventory_sha256"),
        "changed_paths": changed,
        "changed_metadata": metadata,
    }


def record_source_mutation(
    run_dir: Path, state: dict[str, Any], before: dict[str, Any], after: dict[str, Any], stage: str,
) -> None:
    report = {
        "schema_version": "acs-p1-source-mutation/1",
        "run_id": state.get("run_id"),
        "stage": stage,
        "detected_at": now_text(),
        "delta": source_guard_delta(before, after),
        "result": "blocked-no-finalize",
    }
    write_json(run_dir / "source-mutation.json", report)
    state["source_compromised"] = True
    state["source_mutation"] = file_ref(run_dir / "source-mutation.json", run_dir)
    state["gate_status"] = "blocked"
    state["updated_at"] = now_text()
    write_state(run_dir, state)


def verify_source_guard(
    state: dict[str, Any], source_root: Path, run_dir: Path, stage: str,
) -> dict[str, Any]:
    current = collect_source_guard(source_root)
    baseline = load_source_guard(state, run_dir)
    if current.get("inventory_sha256") != baseline.get("inventory_sha256"):
        record_source_mutation(run_dir, state, baseline or {}, current, stage)
        raise SourceMutationError("formal source changed; run blocked without finalize")
    return current


def create_source_snapshot(source_root: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise RunnerError("source snapshot already exists")
    archive = git_bytes(source_root, "archive", "--format=tar", "HEAD")
    destination.mkdir(parents=True)
    files: dict[str, str] = {}
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise RunnerError("source snapshot contains unsafe archive entry")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise RunnerError("source snapshot contains unsupported entry")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(member)
            if stream is None:
                raise RunnerError("source snapshot entry unavailable")
            data = stream.read()
            write_atomic(target, data)
            files[relative.as_posix()] = digest_bytes(data)
    for path in sorted(destination.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    destination.chmod(0o555)
    return {"tree": git_value(source_root, "rev-parse", "HEAD^{tree}"), "files": files}


def audit_workspace(workspace: Path, state: dict[str, Any], run_dir: Path) -> None:
    snapshot_path = validate_ref(state["source_snapshot"], run_dir)
    snapshot = strict_json(snapshot_path.read_bytes())
    baseline = snapshot.get("files", {})
    if not isinstance(baseline, dict):
        raise EvidenceError("source snapshot manifest is invalid")
    secret_paths = []
    for path in workspace.rglob("*"):
        if path.is_symlink():
            raise EvidenceError("workspace symlink output is not accepted as evidence")
        if not path.is_file() or path.name == ".runner-workspace.json":
            continue
        relative = path.relative_to(workspace).as_posix()
        data = path.read_bytes()
        if len(data) > MAX_OUTPUT_BYTES:
            raise EvidenceError("workspace output exceeds runner audit bound")
        if digest_bytes(data) != baseline.get(relative) and secret_findings(data):
            secret_paths.append(relative)
    if secret_paths:
        state["redaction_events"].append({
            "scenario_id": workspace.name,
            "command_id": "workspace-audit",
            "detected": len(secret_paths),
            "paths_sha256": digest(secret_paths),
            "at": now_text(),
        })
        raise EvidenceError("secret-like material detected in private workspace output")


def sandbox_observation() -> dict[str, Any]:
    if os.name != "posix":
        return {"provider": "unavailable", "available": False, "reason": "Windows sandbox not proven"}
    dedicated = Path("/opt/acs/codex-sandbox/bin/bwrap")
    executable = str(dedicated) if dedicated.is_file() else shutil.which("bwrap")
    if not executable:
        return {"provider": "bubblewrap", "available": False, "reason": "bubblewrap missing"}
    path = Path(executable).resolve(strict=True)
    identity = {"provider": "bubblewrap", "path": str(path), "sha256": digest_bytes(path.read_bytes())}
    probe = subprocess.run(
        [str(path), "--ro-bind", "/", "/", "--tmpfs", "/home", "--tmpfs", "/root",
         "--tmpfs", "/tmp", "--tmpfs", "/opt", "--dev", "/dev", "--proc", "/proc",
         "--unshare-user", "--unshare-pid",
         "--unshare-uts", "--unshare-ipc", "--share-net", "--die-with-parent",
         "--new-session", "--", "/bin/true"],
        capture_output=True, timeout=10, check=False,
    )
    if probe.returncode:
        return {**identity, "available": False, "reason": "bubblewrap capability probe failed"}
    return {**identity, "available": True, "version": "capability-probed"}


def verify_sandbox(state: dict[str, Any]) -> dict[str, Any]:
    observed = state.get("sandbox")
    if not isinstance(observed, dict) or observed.get("available") is not True:
        raise SandboxUnavailable("OS-level probe sandbox is unavailable; scenario remains NOT_RUN")
    path = Path(observed.get("path", ""))
    if (not path.is_absolute() or not path.is_file()
            or digest_bytes(path.read_bytes()) != observed.get("sha256")):
        raise EvidenceError("sandbox executable identity changed")
    return observed


def snapshot_files(run_dir: Path, state: dict[str, Any]) -> dict[str, str]:
    path = validate_ref(state["source_snapshot"], run_dir)
    value = strict_json(path.read_bytes())
    files = value.get("files")
    if not isinstance(files, dict):
        raise EvidenceError("source snapshot manifest is invalid")
    return files


def verify_source_snapshot(run_dir: Path, state: dict[str, Any]) -> None:
    expected = snapshot_files(run_dir, state)
    root = run_dir / "source-snapshot"
    actual = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise EvidenceError("source snapshot symlink is forbidden")
        if path.is_file():
            if os.name == "posix" and path.stat().st_mode & 0o222:
                raise EvidenceError("source snapshot file is writable")
            actual[path.relative_to(root).as_posix()] = digest_bytes(path.read_bytes())
        elif path.is_dir() and os.name == "posix" and path.stat().st_mode & 0o222:
            raise EvidenceError("source snapshot directory is writable")
    if actual != expected:
        raise EvidenceError("source snapshot differs from exact HEAD archive")


def sandbox_command(
    state: dict[str, Any], plan: dict[str, Any], run_dir: Path, scenario_id: str,
    command: dict[str, Any], environment: dict[str, str],
    mount_sources: dict[str, Any] | None = None,
) -> tuple[list[str], Path]:
    sandbox = verify_sandbox(state)
    verify_source_snapshot(run_dir, state)
    hidden = {"home", "root", "tmp", "opt"}
    for protected in (Path(state["source_root"]).resolve(), run_dir.resolve()):
        if len(protected.parts) < 2 or protected.parts[1] not in hidden:
            raise SandboxUnavailable(
                "formal source and runner key must reside below a sandbox-hidden top-level"
            )
    output = run_dir / "scenario-output" / scenario_id
    output.mkdir(parents=True, exist_ok=True)
    relative_cwd = Path(command.get("cwd", "."))
    target_cwd = "/mnt" if str(relative_cwd) == "." else "/mnt/" + relative_cwd.as_posix()
    runtime_profile = validate_runtime_profile(plan.get("runtime_profile"))
    runtime_mounts: list[str] = []
    if runtime_profile is not None:
        uid = os.geteuid()
        if mount_sources is None:
            raise SandboxUnavailable("runtime mounts require held descriptors")
        runtime_mounts = [
            "--perms", "0700", "--dir", "/run/user",
            "--perms", "0700", "--dir", f"/run/user/{uid}",
            "--bind", mount_sources["bus"], f"/run/user/{uid}/bus",
            "--perms", "0700", "--dir", "/run/acs-p1",
            "--ro-bind", mount_sources["profile"], "/run/acs-p1/profile.json",
            "--ro-bind", mount_sources["environment"], "/run/acs-p1/runtime",
        ]
    argv = [
        sandbox["path"], "--ro-bind", "/", "/", "--tmpfs", "/home", "--tmpfs", "/root",
        "--tmpfs", "/tmp", "--tmpfs", "/opt", "--tmpfs", "/run",
        "--dev", "/dev", "--proc", "/proc",
        "--unshare-user", "--unshare-pid",
        "--unshare-uts", "--unshare-ipc", "--share-net", "--die-with-parent", "--new-session",
        *runtime_mounts,
        "--ro-bind", str((run_dir / "source-snapshot").resolve()), "/mnt",
        "--bind", str(output.resolve()), "/srv", "--chdir", target_cwd, "--clearenv",
    ]
    for name, value in sorted(environment.items()):
        argv.extend(("--setenv", name, value))
    wrapper = (
        "test -r /mnt && test -w /srv && "
        "! /bin/sh -c 'printf x > /mnt/.runner-write-test' 2>/dev/null && "
        "printf x > /srv/.runner-write-test && rm -f /srv/.runner-write-test && exec \"$@\""
    )
    argv.extend((
        "--", "/bin/sh", "-c", wrapper,
        "p1-sandbox", *command["argv"],
    ))
    return argv, output


def require_external_run_dir(run_dir: Path, source_root: Path) -> None:
    candidate = run_dir.resolve(strict=False)
    source = source_root.resolve(strict=True)
    try:
        candidate.relative_to(source)
    except ValueError:
        return
    raise RunnerError("run directory must be outside the formal source checkout")


def host_fingerprint() -> tuple[str, dict[str, str]]:
    machine_id = ""
    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            machine_id = candidate.read_text(encoding="ascii").strip()
            if machine_id:
                break
        except OSError:
            continue
    facts = {
        "hostname": platform.node(),
        "machine_source_sha256": digest_bytes(machine_id.encode()) if machine_id else "unavailable",
        "os": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "sqlite": sqlite3.sqlite_version,
    }
    fingerprint = digest({"hostname": facts["hostname"], "machine_id": machine_id, "architecture": facts["architecture"]})
    return fingerprint, facts


def load_contract(contract_path: Path) -> dict[str, Any]:
    contract = strict_json(contract_path.read_bytes())
    if not isinstance(contract, dict) or contract.get("schema_version") != "acs-gate-contract/1":
        raise PlanError("invalid Gate contract")
    scenarios = contract.get("gates", {}).get("P1", {}).get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 18 or len(set(scenarios)) != 18:
        raise PlanError("P1 contract must contain exactly 18 scenarios")
    return contract


def validate_command(command: object) -> None:
    if not isinstance(command, dict) or set(command) - COMMAND_KEYS:
        raise PlanError("invalid command fields")
    if not known_text(command.get("command_id")) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", command["command_id"]):
        raise PlanError("bounded command_id required")
    if command.get("kind") not in EVIDENCE_KINDS:
        raise PlanError("unsupported evidence kind")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or len(argv) > 64 or any(not known_text(v) or len(v) > 4096 for v in argv):
        raise PlanError("argv must be a bounded nonempty string list")
    fields = command.get("evidence_fields")
    if not isinstance(fields, list) or not fields or len(set(fields)) != len(fields) or any(v not in EVIDENCE_FIELDS for v in fields):
        raise PlanError("invalid evidence_fields")
    timeout = command.get("timeout_seconds", 300)
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PlanError("invalid command timeout")
    cwd = command.get("cwd", ".")
    if not isinstance(cwd, str) or Path(cwd).is_absolute() or ".." in Path(cwd).parts:
        raise PlanError("command cwd must stay in source checkout")


def validate_plan(plan: object, contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) - PLAN_KEYS or plan.get("schema_version") != PLAN_SCHEMA:
        raise PlanError("invalid plan schema or fields")
    for field in (
        "profile", "node_id", "engineer", "direction", "core_version", "temporal_version",
        "postgresql_version", "protocol_version", "credential_scope", "policy",
    ):
        if not known_text(plan.get(field)):
            raise PlanError(f"known {field} required")
    if stamp(plan.get("expires_at")) <= datetime.now(UTC):
        raise PlanError("plan expiry must be in the future")
    for field in ("harness_versions", "driver_versions"):
        value = plan.get(field)
        if not isinstance(value, dict) or set(value) != {"codex", "opencode"} or not all(known_text(v) for v in value.values()):
            raise PlanError(f"{field} must pin Codex and OpenCode")
    runtime_profile = validate_runtime_profile(plan.get("runtime_profile"))
    if runtime_profile is not None:
        plan_versions = {
            "core": plan["core_version"],
            "provider": {"temporal": plan["temporal_version"]},
            "database": {"postgresql": plan["postgresql_version"]},
            "protocol": plan["protocol_version"],
            "harness": plan["harness_versions"],
            "driver": plan["driver_versions"],
        }
        if (runtime_profile["profile"] != plan["profile"]
                or runtime_profile["node_id"] != plan["node_id"]
                or runtime_profile["direction"] != plan["direction"]
                or runtime_profile["plan_versions_sha256"] != digest(plan_versions)):
            raise PlanError("runtime profile identity or versions differ from plan")
    scenario_map = plan.get("scenarios")
    expected = contract["gates"]["P1"]["scenarios"]
    if not isinstance(scenario_map, dict) or list(scenario_map) != expected:
        raise PlanError("plan scenarios must exactly follow the 18 P1 contract scenarios")
    for scenario_id, commands in scenario_map.items():
        if not isinstance(commands, list) or len(commands) > MAX_COMMANDS:
            raise PlanError(f"{scenario_id}: invalid commands")
        for command in commands:
            validate_command(command)
        ids = [command["command_id"] for command in commands]
        if len(ids) != len(set(ids)):
            raise PlanError(f"{scenario_id}: duplicate command_id")
    if not isinstance(plan.get("prerequisites", {}), dict) or not isinstance(plan.get("review", {}), dict):
        raise PlanError("prerequisites and review must be objects")
    return plan


def plan_complete(commands: list[dict[str, Any]]) -> tuple[bool, str]:
    kinds = {command["kind"] for command in commands}
    fields = {field for command in commands for field in command["evidence_fields"]}
    if kinds != EVIDENCE_KINDS:
        return False, "scenario lacks required command/PostgreSQL/SQLite/Temporal/Driver/OS evidence kinds"
    if fields != set(EVIDENCE_FIELDS):
        return False, "scenario lacks receipt/raw/fault/source/artifact/effect/recovery evidence fields"
    return True, ""


def initialize(plan_path: Path, run_dir: Path, source_root: Path, contract_path: Path) -> dict[str, Any]:
    require_external_run_dir(run_dir, source_root)
    if run_dir.exists():
        raise RunnerError("run directory already exists; use run/audit to resume")
    contract = load_contract(contract_path)
    plan_bytes = plan_path.read_bytes()
    if secret_findings(plan_bytes):
        raise PlanError("secret-like material is forbidden in the runner plan")
    plan = validate_plan(strict_json(plan_bytes), contract)
    runtime_profile = validate_runtime_profile(plan.get("runtime_profile"))
    if (runtime_profile is not None and runtime_profile["source_root_sha256"]
            != digest(str(source_root.resolve(strict=True)))):
        raise PlanError("runtime profile source root differs from runner source")
    identity = source_identity(source_root)
    guard = collect_source_guard(source_root)
    fingerprint, os_facts = host_fingerprint()
    machine_id = "machine-" + fingerprint[:20]
    observed = now_text()
    expiry = stamp(plan["expires_at"]).isoformat()
    run_id = "p1-run-" + secrets.token_hex(16)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{run_dir.name}.stage-", dir=run_dir.parent))
    stage.chmod(0o700)
    try:
        create_state_key(stage)
        write_atomic(stage / "plan.json", plan_bytes)
        snapshot = create_source_snapshot(source_root, stage / "source-snapshot")
        write_json(stage / "source-snapshot.json", {
        "schema_version": "acs-p1-source-snapshot/1",
        "source_commit": identity.commit,
        "source_tree": identity.tree,
        "archive_tree": snapshot["tree"],
        "files": snapshot["files"],
        })
        guard_summary = persist_source_guard(stage, guard)
        raw_path = stage / "evidence" / "machine" / "raw-os.json"
        write_json(raw_path, {"schema_version": "acs-runner-os-observation/1", **os_facts})
        raw_ref = file_ref(raw_path, stage)
        observation_path = stage / "evidence" / "machine" / "observation.json"
        observation = {
        "schema_version": MACHINE_SCHEMA,
        "machine_id": machine_id,
        "node_id": plan["node_id"],
        "profile": plan["profile"],
        "host_fingerprint": fingerprint,
        "os": os_facts["os"],
        "observed_at": observed,
        "expires_at": expiry,
        "evidence_class": "directly_verified",
        "evidence": raw_ref,
        }
        write_json(observation_path, observation)
        binding = {
        "profile": plan["profile"],
        "machines": [machine_id],
        "nodes": [plan["node_id"]],
        "os": {machine_id: os_facts["os"]},
        "core": plan["core_version"],
        "provider": {"temporal": plan["temporal_version"]},
        "driver": plan["driver_versions"],
        "harness": plan["harness_versions"],
        "database": {"postgresql": plan["postgresql_version"], "sqlite": os_facts["sqlite"]},
        "protocol": plan["protocol_version"],
        "credential_scope": plan["credential_scope"],
        "policy": plan["policy"],
        "direction": plan["direction"],
        "expires_at": expiry,
        "machine_evidence": {machine_id: file_ref(observation_path, stage)},
        "session_evidence": [],
        }
        version_binding = {
        "core": binding["core"],
        "provider": binding["provider"],
        "database": binding["database"],
        "protocol": binding["protocol"],
        "harness": binding["harness"],
        "driver": binding["driver"],
        "os": binding["os"],
        }
        state = {
        "schema_version": STATE_SCHEMA,
        "run_id": run_id,
        "created_at": observed,
        "updated_at": observed,
        "plan_sha256": digest_bytes(plan_bytes),
        "contract_sha256": digest_bytes(contract_path.read_bytes()),
        "contract_revision": contract["contract_revision"],
        "source_commit": identity.commit,
        "source_tree": identity.tree,
        "source_root": str(source_root.resolve()),
        "run_dir": str(run_dir.resolve()),
        "source_guard": guard_summary,
        "source_snapshot": file_ref(stage / "source-snapshot.json", stage),
        "source_compromised": False,
        "sandbox": sandbox_observation(),
        "runtime_profile": runtime_profile,
        "machine_id": machine_id,
        "host_fingerprint": fingerprint,
        "node_id": plan["node_id"],
        "binding": binding,
        "binding_sha256": digest(binding),
        "version_binding": version_binding,
        "scenarios": {sid: {"status": "not_run", "commands": {}, "reason": "not executed"} for sid in plan["scenarios"]},
        "redaction_events": [],
        }
        write_state(stage, state)
        finalize(stage, source_root, contract_path, allow_pass=False)
        if run_dir.exists():
            raise RunnerError("run directory appeared during initialization")
        os.replace(stage, run_dir)
        if os.name == "posix":
            parent_fd = os.open(run_dir.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        return load_state(run_dir)
    except BaseException:
        remove_private_stage(stage)
        raise


def load_run(run_dir: Path, source_root: Path, contract_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    require_external_run_dir(run_dir, source_root)
    state = load_state(run_dir)
    plan_bytes = (run_dir / "plan.json").read_bytes()
    contract_bytes = contract_path.read_bytes()
    contract = load_contract(contract_path)
    plan = validate_plan(strict_json(plan_bytes), contract)
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise RunnerError("invalid run state")
    if state.get("source_compromised") is True:
        raise SourceMutationError("run is blocked by a prior formal source mutation")
    if state.get("plan_sha256") != digest_bytes(plan_bytes) or state.get("contract_sha256") != digest_bytes(contract_bytes):
        raise RunnerError("plan or contract digest changed")
    current_guard = collect_source_guard(source_root)
    baseline_guard = load_source_guard(state, run_dir)
    if current_guard.get("inventory_sha256") != baseline_guard.get("inventory_sha256"):
        record_source_mutation(run_dir, state, baseline_guard or {}, current_guard, "resume-preflight")
        raise SourceMutationError("mixed or changed Git baseline/source inventory")
    if (state.get("source_commit"), state.get("source_tree")) != (
        current_guard.get("head"), current_guard.get("tree"),
    ):
        record_source_mutation(run_dir, state, baseline_guard, current_guard, "resume-identity")
        raise SourceMutationError("mixed or changed Git baseline")
    validate_ref(state.get("source_snapshot"), run_dir)
    if state.get("binding_sha256") != digest(state.get("binding")):
        raise RunnerError("binding digest changed")
    expected_versions = {
        "core": state["binding"]["core"],
        "provider": state["binding"]["provider"],
        "database": state["binding"]["database"],
        "protocol": state["binding"]["protocol"],
        "harness": state["binding"]["harness"],
        "driver": state["binding"]["driver"],
        "os": state["binding"]["os"],
    }
    if state.get("version_binding") != expected_versions:
        raise RunnerError("version binding changed")
    current_runtime_profile = validate_runtime_profile(plan.get("runtime_profile"))
    if (current_runtime_profile is not None and current_runtime_profile["source_root_sha256"]
            != digest(str(source_root.resolve(strict=True)))):
        raise RunnerError("runtime profile source root changed")
    if state.get("runtime_profile") != current_runtime_profile:
        raise RunnerError("runtime profile binding changed")
    machine_refs = state["binding"].get("machine_evidence", {})
    if set(machine_refs) != {state.get("machine_id")}:
        raise RunnerError("P1 runner accepts exactly one observed physical machine")
    for ref in machine_refs.values():
        validate_ref(ref, run_dir)
    current_fingerprint, _current_facts = host_fingerprint()
    if (state.get("host_fingerprint") != current_fingerprint
            or state.get("machine_id") != "machine-" + current_fingerprint[:20]):
        raise RunnerError("physical Machine observation changed")
    return state, plan, contract


def probe_environment(state: dict[str, Any], scenario_id: str, command: dict[str, Any]) -> dict[str, str]:
    environment = {
        "ACS_GATE_RUN_ID": state["run_id"],
        "ACS_GATE_SCENARIO_ID": scenario_id,
        "ACS_GATE_COMMAND_ID": command["command_id"],
        "ACS_GATE_EVIDENCE_KIND": command["kind"],
        "ACS_GATE_SOURCE_COMMIT": state["source_commit"],
        "ACS_GATE_SOURCE_TREE": state["source_tree"],
        "ACS_GATE_BINDING_SHA256": state["binding_sha256"],
        "ACS_GATE_PROFILE": state["binding"]["profile"],
        "ACS_GATE_MACHINE_ID": state["machine_id"],
        "ACS_GATE_NODE_ID": state["node_id"],
        "ACS_GATE_DIRECTION": state["binding"]["direction"],
        "ACS_GATE_EXPIRES_AT": state["binding"]["expires_at"],
        "ACS_GATE_VERSIONS_JSON": canonical(state["version_binding"]).decode(),
        "ACS_GATE_SOURCE_SNAPSHOT": "/mnt",
        "ACS_GATE_OUTPUT": "/srv",
    }
    if state.get("runtime_profile") is not None:
        environment["ACS_GATE_RUNTIME_PROFILE"] = "/run/acs-p1/profile.json"
        environment["ACS_GATE_RUNTIME_ROOT"] = "/run/acs-p1/runtime"
        environment["ACS_GATE_NETWORK_MODE"] = "host_loopback_providers"
        environment["XDG_RUNTIME_DIR"] = f"/run/user/{os.geteuid()}"
        environment["DBUS_SESSION_BUS_ADDRESS"] = (
            f"unix:path=/run/user/{os.geteuid()}/bus"
        )
    return environment


def validate_probe(
    value: object,
    state: dict[str, Any],
    scenario_id: str,
    command: dict[str, Any],
    started: datetime,
    finished: datetime,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != PROBE_SCHEMA or value.get("status") != "passed":
        raise EvidenceError("probe did not return a passed runner result")
    expected = {
        "run_id": state["run_id"], "scenario_id": scenario_id,
        "command_id": command["command_id"], "evidence_kind": command["kind"],
        "source_commit": state["source_commit"], "source_tree": state["source_tree"],
        "binding_sha256": state["binding_sha256"], "profile": state["binding"]["profile"],
        "machine_id": state["machine_id"], "node_id": state["node_id"],
        "direction": state["binding"]["direction"],
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise EvidenceError("probe identity, baseline, machine or binding mismatch")
    if value.get("versions") != state["version_binding"]:
        raise EvidenceError("probe version binding mismatch")
    observed = stamp(value.get("observed_at"))
    expiry = stamp(value.get("expires_at"))
    if observed < started or observed > finished or not finished < expiry <= stamp(state["binding"]["expires_at"]):
        raise EvidenceError("probe time interval is stale, future or outside binding")
    for field in ID_FIELDS:
        values = value.get(field)
        if not isinstance(values, list) or not values or len(values) != len(set(values)) or not all(known_text(v) for v in values):
            raise EvidenceError(f"probe requires unique {field}")
    receipts = value.get("receipt_ids")
    if "receipts" in command["evidence_fields"] and (
        not isinstance(receipts, list) or not receipts or len(receipts) != len(set(receipts))
        or not all(known_text(v) for v in receipts)
    ):
        raise EvidenceError("receipt evidence requires concrete receipt IDs")
    facts = value.get("facts")
    if not isinstance(facts, dict):
        raise EvidenceError("probe facts required")
    if "fault_injection" in command["evidence_fields"] and facts.get("fault_injected") is not True:
        raise EvidenceError("fault injection evidence is not affirmative")
    for field, flag in READBACK_FLAGS.items():
        if field in command["evidence_fields"] and facts.get(flag) is not True:
            raise EvidenceError(f"{field} lacks affirmative readback")
    return value


def execute_command(
    state: dict[str, Any], plan: dict[str, Any], scenario_id: str,
    command: dict[str, Any], run_dir: Path, source_root: Path,
) -> dict[str, Any]:
    before = verify_source_guard(state, source_root, run_dir, "command-preflight")
    evidence_directory = digest(command["command_id"])
    source_text = str(source_root.resolve(strict=True))
    if any(source_text.casefold() in value.casefold() for value in command["argv"]):
        raise EvidenceError("probe argv must not receive the formal source or gates path")
    environment = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ"}
        and source_text.casefold() not in value.casefold()
    }
    if os.name == "posix":
        environment["PATH"] = "/usr/bin:/bin"
    environment.update(probe_environment(state, scenario_id, command))
    with pinned_runtime_mounts(plan) as (mount_sources, pass_fds):
        wrapped_argv, output = sandbox_command(
            state, plan, run_dir, scenario_id, command, environment, mount_sources,
        )
        assert_runtime_mounts_unchanged(plan, mount_sources, pass_fds)
        started = datetime.now(UTC)
        try:
            result = subprocess.run(
                wrapped_argv, cwd=run_dir, env={}, capture_output=True,
                timeout=command.get("timeout_seconds", 300), check=False,
                pass_fds=pass_fds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvidenceError(f"probe execution failed: {type(error).__name__}") from error
    finished = datetime.now(UTC)
    after = collect_source_guard(source_root)
    if after.get("inventory_sha256") != before.get("inventory_sha256"):
        record_source_mutation(run_dir, state, before, after, "command-postflight")
        raise SourceMutationError("probe changed formal source; blocked without finalize")
    verify_source_snapshot(run_dir, state)
    audit_workspace(output, state, run_dir)
    if len(result.stdout) > MAX_OUTPUT_BYTES or len(result.stderr) > MAX_OUTPUT_BYTES:
        raise EvidenceError("probe output exceeds runner bound")
    findings = secret_findings(result.stdout) + secret_findings(result.stderr)
    if findings:
        state["redaction_events"].append({
            "scenario_id": scenario_id, "command_id": command["command_id"],
            "detected": len(findings), "at": now_text(),
        })
        failure = run_dir / "evidence" / scenario_id / evidence_directory / "redacted-failure.txt"
        write_atomic(failure, redacted(result.stdout + b"\n" + result.stderr))
        raise EvidenceError("secret-like material detected and redacted")
    if result.returncode != 0:
        failure = run_dir / "evidence" / scenario_id / evidence_directory / "failure.txt"
        write_atomic(failure, result.stdout + b"\n" + result.stderr)
        raise EvidenceError(f"probe command exited {result.returncode}")
    if result.stderr:
        raise EvidenceError("successful probe emitted unmanaged stderr")
    probe = validate_probe(strict_json(result.stdout), state, scenario_id, command, started, finished)
    output_path = run_dir / "evidence" / scenario_id / evidence_directory / "stdout.json"
    write_atomic(output_path, result.stdout)
    output_ref = file_ref(output_path, run_dir)
    return {
        "status": "passed", "kind": command["kind"],
        "evidence_fields": command["evidence_fields"], "argv_sha256": digest(command["argv"]),
        "output": output_ref, "observed_at": probe["observed_at"],
        "expires_at": probe["expires_at"],
        "operation_ids": probe["operation_ids"], "message_ids": probe["message_ids"],
        "event_ids": probe["event_ids"], "receipt_ids": probe.get("receipt_ids", []),
        "observer": probe.get("observer"), "owner": probe.get("owner"),
    }


def scenario_record(state: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    scenario = state["scenarios"][scenario_id]
    if scenario["status"] != "passed":
        return {"scenario_id": scenario_id, "status": scenario["status"]}
    commands = list(scenario["commands"].values())
    observers, owners = {item["observer"] for item in commands}, {item["owner"] for item in commands}
    if len(observers) != 1 or len(owners) != 1 or not all(known_text(v) for v in (*observers, *owners)):
        raise EvidenceError("scenario observer/owner identity is inconsistent")
    output_refs = [item["output"] for item in commands]
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "status": "passed",
        "source_baseline": state["source_commit"],
        "binding_sha256": state["binding_sha256"],
        "evidence_class": "directly_verified",
        "evidence_state": "complete",
        "observed_at": max(item["observed_at"] for item in commands),
        "expires_at": min(item["expires_at"] for item in commands),
        "command_ids": list(scenario["commands"]),
        "operation_ids": sorted({v for item in commands for v in item["operation_ids"]}),
        "message_ids": sorted({v for item in commands for v in item["message_ids"]}),
        "event_ids": sorted({v for item in commands for v in item["event_ids"]}),
        "observer": next(iter(observers)),
        "owner": next(iter(owners)),
        "unresolved_items": [],
    }
    for field in EVIDENCE_FIELDS:
        if field == "raw_outputs":
            record[field] = output_refs
        else:
            record[field] = [item["output"] for item in commands if field in item["evidence_fields"]]
    return record


def audit_commands(state: dict[str, Any], plan: dict[str, Any], run_dir: Path) -> None:
    for scenario_id, scenario in state["scenarios"].items():
        planned = {command["command_id"]: command for command in plan["scenarios"][scenario_id]}
        if set(scenario.get("commands", {})) - set(planned):
            raise EvidenceError("stored command is absent from the sealed plan")
        for command_id, result in scenario.get("commands", {}).items():
            command = planned[command_id]
            if (result.get("kind") != command["kind"]
                    or result.get("evidence_fields") != command["evidence_fields"]
                    or result.get("argv_sha256") != digest(command["argv"])):
                raise EvidenceError("stored command differs from the sealed plan")
            path = validate_ref(result.get("output"), run_dir)
            expected_path = (
                Path("evidence") / scenario_id / digest(command_id) / "stdout.json"
            ).as_posix()
            if result["output"].get("path") != expected_path:
                raise EvidenceError("stored evidence path differs from command identity")
            value = strict_json(path.read_bytes())
            if (value.get("run_id") != state["run_id"] or value.get("scenario_id") != scenario_id
                    or value.get("command_id") != command_id or value.get("source_commit") != state["source_commit"]
                    or value.get("source_tree") != state["source_tree"]
                    or value.get("binding_sha256") != state["binding_sha256"]):
                raise EvidenceError("stored evidence no longer binds this run")


def invoke_validator(record_path: Path, run_dir: Path, source_root: Path, require_passed: bool) -> dict[str, Any]:
    validator = source_root / "tools" / "runtime" / "validate_gate.py"
    command = [sys.executable, str(validator), str(record_path), "--evidence-root", str(run_dir)]
    if require_passed:
        command.append("--require-passed")
    result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    try:
        output = strict_json(result.stdout)
    except EvidenceError:
        output = {"valid": False, "errors": ["validator returned invalid JSON"]}
    return {"argv_sha256": digest(command), "exit_code": result.returncode, "output": output, "invoked_at": now_text()}


def build_manifest(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    files = {}
    for path in sorted(run_dir.rglob("*")):
        relative = path.relative_to(run_dir)
        if (path.is_file() and path.name not in {"RUN-MANIFEST.json", STATE_KEY_NAME}
                and relative.parts[0] not in {"source-snapshot", "workspaces"}):
            files[path.relative_to(run_dir).as_posix()] = digest_bytes(path.read_bytes())
    return {
        "schema_version": MANIFEST_SCHEMA,
        "run_id": state["run_id"],
        "source_commit": state["source_commit"],
        "source_tree": state["source_tree"],
        "profile": state["binding"]["profile"],
        "machine_id": state["machine_id"],
        "node_id": state["node_id"],
        "binding_sha256": state["binding_sha256"],
        "gate_status": state.get("gate_status", "not_run"),
        "files": files,
        "created_at": now_text(),
    }


def finalize(run_dir: Path, source_root: Path, contract_path: Path, *, allow_pass: bool = True) -> dict[str, Any]:
    state, plan, contract = load_run(run_dir, source_root, contract_path)
    audit_commands(state, plan, run_dir)
    scenario_records = [scenario_record(state, sid) for sid in contract["gates"]["P1"]["scenarios"]]
    statuses = {item["status"] for item in scenario_records}
    candidate_pass = allow_pass and statuses == {"passed"}
    status = "passed" if candidate_pass else "not_run" if statuses == {"not_run"} else "blocked"
    record = {
        "schema_version": GATE_RECORD_SCHEMA,
        "contract_revision": contract["contract_revision"],
        "gate": "P1",
        "status": status,
        "source_baseline": state["source_commit"],
        "engineer": plan["engineer"],
        "binding": state["binding"],
        "scenarios": scenario_records,
        "prerequisites": plan.get("prerequisites", {}),
        "review": plan.get("review", {}),
    }
    record_path = run_dir / "gate-record.json"
    write_json(record_path, record)
    validation = invoke_validator(record_path, run_dir, source_root, require_passed=candidate_pass)
    if candidate_pass and (validation["exit_code"] != 0 or not validation["output"].get("valid")):
        record["status"] = "blocked"
        write_json(record_path, record)
        validation = invoke_validator(record_path, run_dir, source_root, require_passed=False)
    state["gate_status"] = record["status"]
    state["updated_at"] = now_text()
    write_state(run_dir, state)
    write_json(run_dir / "validation.json", validation)
    write_json(run_dir / "redaction-audit.json", {
        "schema_version": "acs-p1-redaction-audit/1",
        "run_id": state["run_id"], "events": state["redaction_events"],
        "status": "passed" if not state["redaction_events"] else "blocked",
    })
    write_json(run_dir / "RUN-MANIFEST.json", build_manifest(run_dir, state))
    return record


def run_scenario(
    run_dir: Path, source_root: Path, contract_path: Path, scenario_id: str,
) -> dict[str, Any]:
    state, plan, contract = load_run(run_dir, source_root, contract_path)
    if scenario_id not in contract["gates"]["P1"]["scenarios"]:
        raise PlanError("unknown P1 scenario")
    commands = plan["scenarios"][scenario_id]
    complete, reason = plan_complete(commands)
    if not complete:
        state["scenarios"][scenario_id] = {"status": "not_run", "commands": {}, "reason": reason}
        state["updated_at"] = now_text()
        write_state(run_dir, state)
        finalize(run_dir, source_root, contract_path, allow_pass=False)
        raise EvidenceError(reason)
    scenario = state["scenarios"][scenario_id]
    scenario["reason"] = "running"
    for command in commands:
        command_id = command["command_id"]
        if command_id in scenario["commands"]:
            validate_ref(scenario["commands"][command_id]["output"], run_dir)
            continue
        try:
            scenario["commands"][command_id] = execute_command(
                state, plan, scenario_id, command, run_dir, source_root,
            )
            write_state(run_dir, state)
        except SandboxUnavailable as error:
            scenario["status"] = "not_run"
            scenario["reason"] = str(error)
            state["updated_at"] = now_text()
            write_state(run_dir, state)
            finalize(run_dir, source_root, contract_path, allow_pass=False)
            raise
        except SourceMutationError as error:
            scenario["status"] = "blocked"
            scenario["reason"] = str(error)
            state["source_compromised"] = True
            state["gate_status"] = "blocked"
            state["updated_at"] = now_text()
            write_state(run_dir, state)
            raise
        except EvidenceError as error:
            scenario["status"] = "blocked"
            scenario["reason"] = str(error)
            state["updated_at"] = now_text()
            write_state(run_dir, state)
            finalize(run_dir, source_root, contract_path, allow_pass=False)
            raise
    scenario["status"] = "passed"
    scenario["reason"] = "complete direct evidence"
    state["updated_at"] = now_text()
    write_state(run_dir, state)
    try:
        return finalize(run_dir, source_root, contract_path)
    except (EvidenceError, RunnerError) as error:
        state["scenarios"][scenario_id]["status"] = "blocked"
        state["scenarios"][scenario_id]["reason"] = str(error)
        state["updated_at"] = now_text()
        write_state(run_dir, state)
        finalize(run_dir, source_root, contract_path, allow_pass=False)
        raise


def audit_run(run_dir: Path, source_root: Path, contract_path: Path) -> dict[str, Any]:
    state, plan, _contract = load_run(run_dir, source_root, contract_path)
    audit_commands(state, plan, run_dir)
    for path in run_dir.rglob("*"):
        relative = path.relative_to(run_dir)
        if (path.is_file() and path.name not in {"RUN-MANIFEST.json", STATE_KEY_NAME}
                and relative.parts[0] not in {"source-snapshot", "workspaces"}
                and secret_findings(path.read_bytes())):
            raise EvidenceError(f"secret-like material in {path.relative_to(run_dir)}")
    for workspace in ((run_dir / "scenario-output").glob("*")
                      if (run_dir / "scenario-output").exists() else ()):
        if workspace.is_dir():
            audit_workspace(workspace, state, run_dir)
    manifest = strict_json((run_dir / "RUN-MANIFEST.json").read_bytes())
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("run_id") != state["run_id"]:
        raise EvidenceError("run manifest identity mismatch")
    for name, expected in manifest.get("files", {}).items():
        path = run_dir / name
        if not path.is_file() or digest_bytes(path.read_bytes()) != expected:
            raise EvidenceError("run manifest file digest mismatch")
    return finalize(run_dir, source_root, contract_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--plan", type=Path, required=True)
    init.add_argument("--run-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--scenario", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source_root = args.source_root.resolve(strict=True)
        contract_path = args.contract.resolve(strict=True)
        if args.action == "init":
            state = initialize(args.plan.resolve(strict=True), args.run_dir.absolute(), source_root, contract_path)
            output = {"status": "not_run", "run_id": state["run_id"], "run_dir": str(args.run_dir.absolute())}
        elif args.action == "run":
            record = run_scenario(args.run_dir.resolve(strict=True), source_root, contract_path, args.scenario)
            output = {"status": record["status"], "scenario": args.scenario}
        else:
            record = audit_run(args.run_dir.resolve(strict=True), source_root, contract_path)
            output = {"status": record["status"], "audit": "passed"}
        print(json.dumps(output, sort_keys=True))
        return 0
    except (OSError, RunnerError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)[:300]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
