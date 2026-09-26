"""Read-only native delegation inventory for a bounded no-model P1 component."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
)
from runtime.delivery import DeliveryDispatcher
from runtime.domain import DomainAuthority
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import (
    OpenCodeLaunchProfile,
    OpenCodeNativeDriver,
    reviewed_private_external_allow,
)
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
    CodexHostRunPolicy,
    HostNodeRejected,
    _sha256_owner_file,
)
from runtime.p1_opencode_host_node import OpenCodeHostNodeEndpoint, OpenCodeHostRequest
from runtime.systemd_supervisor import SystemdUserSupervisor

SCENARIO = "P1-NATIVE-MULTIAGENT-OFF"
CODEX_SHA256 = "f8786262ebc0fa1337448a2977332beadec66c8d0cda0ce973c7849766d7943c"
CODEX_SIZE = 258_597_984
CODEX_CATALOG_SHA256 = "c3172f5fa1a69329d1aba8ca6328baf08b07927a100ce67c7d18d4c3d7ac1592"
OPENCODE_SHA256 = "87bd160e053af86b5b409daabf71f8dc05bbc3a2a3a5f563f36011cdf706a999"
OPENCODE_SIZE = 184_825_984
OPENCODE_SCHEMA_SHA256 = "cf12e9739510a196c7f25eb938555cfb66d901957f66f840a12d4489ae440ac3"


class NativeInventoryRejected(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def codex_effective_inventory(
    config_bytes: bytes,
    active_settings: dict[str, Any],
    feature_reads: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    permission_profile: str,
    cwd: str,
) -> dict[str, Any]:
    """Require the actual 0.153.2 feature pages and active thread settings."""
    try:
        config = tomllib.loads(config_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise NativeInventoryRejected("Codex pinned config is malformed") from exc
    features = config.get("features")
    if (not isinstance(active_settings, dict)
            or not isinstance(features, dict)
            or any(features.get(name) is not False for name in (
                "multi_agent", "multi_agent_v2", "shell_tool",
                "request_permissions_tool", "apps", "plugins",
            ))
            or config.get("approval_policy") != "never"
            or config.get("default_permissions") != permission_profile
            or active_settings.get("activePermissionProfile", {}).get("id")
            != permission_profile
            or active_settings.get("approvalPolicy") != "never"
            or Path(active_settings.get("cwd", "")) != Path(cwd)):
        raise NativeInventoryRejected("Codex config or active permission boundary is not disabled")
    if not 1 <= len(feature_reads) <= 20:
        raise NativeInventoryRejected("Codex effective feature pagination is incomplete")
    states: dict[str, bool] = {}
    expected_cursor = None
    for index, (params, page) in enumerate(feature_reads):
        if (not isinstance(params, dict) or not isinstance(page, dict)
                or params.get("limit") != 100
                or params.get("cursor") != expected_cursor
                or not isinstance(page.get("data"), list)
                or len(page["data"]) > 100):
            raise NativeInventoryRejected("Codex feature page identity or bound changed")
        for item in page["data"]:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("name"), str)
                    or type(item.get("enabled")) is not bool
                    or item["name"] in states):
                raise NativeInventoryRejected("Codex effective feature inventory is malformed")
            states[item["name"]] = item["enabled"]
        expected_cursor = page.get("nextCursor")
        if index < len(feature_reads) - 1 and not isinstance(expected_cursor, str):
            raise NativeInventoryRejected("Codex feature page ended before final read")
    if expected_cursor:
        raise NativeInventoryRejected("Codex feature pagination has an unread page")
    if any(states.get(name) is not False for name in ("multi_agent", "multi_agent_v2")):
        raise NativeInventoryRejected("Codex effective native delegation is not disabled")
    return {
        "native_version": "0.153.2",
        "config_sha256": _sha(config_bytes),
        "active_permission_profile": permission_profile,
        "effective_features_sha256": _sha(_canonical(states)),
        "effective_feature_count": len(states),
        "effective_feature_pages": len(feature_reads),
        "multi_agent": False,
        "multi_agent_v2": False,
        "shell_tool": False,
        "request_permissions_tool": False,
        "native_tool_inventory_exposed": False,
    }


def opencode_effective_inventory(
    config: dict[str, Any],
    agents: list[dict[str, Any]],
    tool_ids: list[str],
    *,
    profile: Any,
) -> dict[str, Any]:
    """Re-read the effective selected Agent and all native tool IDs."""
    if not isinstance(config, dict) or not isinstance(config.get("agent"), dict):
        raise NativeInventoryRejected("OpenCode effective config is malformed")
    selected = config["agent"].get(profile.agent, {})
    if not isinstance(selected, dict):
        raise NativeInventoryRejected("OpenCode selected Agent config is malformed")
    if (config.get("permission") != {"*": "deny", "task": "deny"}
            or selected.get("permission") != {"*": "deny", "task": "deny"}
            or config.get("default_agent") != profile.agent
            or config.get("plugin", []) != [] or config.get("mcp", {}) != {}):
        raise NativeInventoryRejected("OpenCode global or selected Agent config is not deny-all")
    if (not isinstance(agents, list) or len(agents) > 128
            or any(not isinstance(agent, dict) for agent in agents)
            or not isinstance(tool_ids, list) or not 1 <= len(tool_ids) <= 4096
            or any(not isinstance(tool, str) or not tool or len(tool) > 256
                   for tool in tool_ids)
            or len(set(tool_ids)) != len(tool_ids)):
        raise NativeInventoryRejected("OpenCode effective Agent/tool inventory is malformed")
    matches = [agent for agent in agents if agent.get("name") == profile.agent]
    if len(matches) != 1:
        raise NativeInventoryRejected("OpenCode selected Agent is not unique")
    rules = matches[0].get("permission")
    if (not isinstance(rules, list) or not rules
            or any(not isinstance(rule, dict) or rule.get("action") not in (
                "allow", "ask", "deny",
            ) for rule in rules)):
        raise NativeInventoryRejected("OpenCode effective Agent rules are malformed")
    last_deny = next((index for index in range(len(rules) - 1, -1, -1)
                      if rules[index] == {"permission": "*", "pattern": "*",
                                          "action": "deny"}), None)
    if last_deny is None:
        raise NativeInventoryRejected("OpenCode effective Agent lacks final deny-all")
    private_allow_count = 0
    for rule in rules[last_deny + 1:]:
        if rule["action"] == "deny":
            continue
        if (rule.get("permission") == "external_directory"
                and rule.get("action") == "allow"
                and reviewed_private_external_allow(profile, rule.get("pattern"))):
            private_allow_count += 1
            continue
        raise NativeInventoryRejected("OpenCode effective Agent enables an unreviewed tool")
    names = [agent.get("name") for agent in agents]
    if (any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names)):
        raise NativeInventoryRejected("OpenCode Agent names are malformed")
    return {
        "native_version": "1.18.30",
        "effective_config_sha256": _sha(_canonical(config)),
        "effective_permission_sha256": _sha(_canonical({
            "global": config["permission"],
            "selected": selected["permission"],
            "rules": rules,
        })),
        "selected_agent": profile.agent,
        "effective_agents_sha256": _sha(_canonical(sorted(names))),
        "effective_agent_count": len(names),
        "effective_rules_sha256": _sha(_canonical(rules)),
        "final_deny_index": last_deny,
        "private_external_directory_allows": private_allow_count,
        "effective_tool_ids_sha256": _sha(_canonical(sorted(tool_ids))),
        "effective_tool_count": len(tool_ids),
        "task_tool_present_but_denied": "task" in tool_ids,
    }


def capture_codex_bootstrap(
    driver: CodexAppServerDriver, operation: AuthorizedOperation,
) -> dict[str, Any]:
    """Observe the production Driver's native bootstrap; send no turn/start."""
    if driver.profile.version != "0.153.2":
        raise NativeInventoryRejected("Codex native profile version differs")
    original_rpc = driver._rpc
    active: dict[str, Any] | None = None
    reads: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def observe(item, method, params, **kwargs):
        nonlocal active
        result = original_rpc(item, method, params, **kwargs)
        if method == "thread/start":
            active = result
        elif method == "experimentalFeature/list":
            reads.append((dict(params), result))
        return result

    driver._rpc = observe
    try:
        driver.spawn(operation)
    finally:
        driver._rpc = original_rpc
    if active is None:
        raise NativeInventoryRejected("Codex actual thread settings were not read")
    config_bytes = (Path(driver.profile.codex_home) / "config.toml").read_bytes()
    summary = codex_effective_inventory(
        config_bytes, active, reads,
        permission_profile=driver.profile.permission_profile,
        cwd=driver.profile.cwd,
    )
    with driver.journal._connect() as connection:
        turns = connection.execute(
            "SELECT count(*) FROM driver_events WHERE kind='rpc_dispatch' "
            "AND body LIKE '%turn/start%'",
        ).fetchone()[0]
    if turns:
        raise NativeInventoryRejected("Codex no-model bootstrap dispatched a turn")
    summary["model_turn_count"] = 0
    summary["native_executable_sha256"] = driver.profile.executable_sha256
    summary["native_session_ref"] = driver.session_id
    summary["_witness"] = {
        "active_settings": {
            key: active.get(key) for key in (
                "activePermissionProfile", "approvalPolicy", "cwd",
            )
        },
        "feature_reads": reads,
    }
    return summary


def capture_opencode_bootstrap(
    driver: OpenCodeNativeDriver, operation: AuthorizedOperation,
) -> dict[str, Any]:
    """Observe production /config, /agent and /tool/ids without prompt_async."""
    if driver.profile.version != "1.18.30":
        raise NativeInventoryRejected("OpenCode native profile version differs")
    original_http = driver._http
    views: dict[str, Any] = {}

    def observe(item, method, path, payload=None, **kwargs):
        status, value = original_http(item, method, path, payload, **kwargs)
        if method == "GET" and path in ("/config", "/agent", "/experimental/tool/ids"):
            views[path] = value
        return status, value

    driver._http = observe
    try:
        driver.spawn(operation)
    finally:
        driver._http = original_http
    if set(views) != {"/config", "/agent", "/experimental/tool/ids"}:
        raise NativeInventoryRejected("OpenCode actual effective inventory was not read")
    summary = opencode_effective_inventory(
        views["/config"], views["/agent"], views["/experimental/tool/ids"],
        profile=driver.profile,
    )
    with driver.journal._connect() as connection:
        prompts = connection.execute(
            "SELECT count(*) FROM driver_events WHERE kind='http_dispatch' "
            "AND body LIKE '%prompt_async%'",
        ).fetchone()[0]
    if prompts:
        raise NativeInventoryRejected("OpenCode no-model bootstrap dispatched a prompt")
    summary["model_prompt_count"] = 0
    summary["config_sha256"] = driver.profile.config_sha256
    summary["native_executable_sha256"] = driver.profile.executable_sha256
    summary["native_session_ref"] = driver.session_id
    config = views["/config"]
    summary["_witness"] = {
        "config": {
            "permission": config.get("permission"),
            "default_agent": config.get("default_agent"),
            "agent": {driver.profile.agent: {
                "permission": config.get("agent", {}).get(driver.profile.agent, {}).get("permission"),
            }},
            "plugin": config.get("plugin", []),
            "mcp": config.get("mcp", {}),
        },
        "agents": [{"name": agent.get("name"), "permission": agent.get("permission")}
                   for agent in views["/agent"]],
        "tool_ids": views["/experimental/tool/ids"],
    }
    return summary


def reject_host_enablement_request() -> None:
    """Neither HostNode request schema has a native delegation control field."""
    for model in (CodexHostRequest, OpenCodeHostRequest):
        if (model.model_config.get("extra") != "forbid"
                or "native_delegation_enabled" in model.model_fields
                or "agent" in model.model_fields
                or "tools" in model.model_fields):
            raise NativeInventoryRejected("HostNode exposes a native delegation override")


def _copy_pinned(source: Path, target: Path, *, expected_sha256: str,
                 expected_size: int | None = None, mode: int = 0o500) -> dict[str, Any]:
    """Pin mutable source bytes, then independently hash the private copy."""
    if (not source.is_absolute() or ".." in source.parts
            or source.resolve(strict=True) != source
            or not target.parent.is_dir() or target.exists() or target.is_symlink()):
        raise NativeInventoryRejected("reviewed native source or private target path differs")
    parent = target.parent.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700):
        raise NativeInventoryRejected("private native copy parent is not owner-only")

    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_mode, info.st_nlink)

    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    target_fd = None
    created = False
    try:
        before = os.fstat(source_fd)
        current = source.stat(follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid() or before.st_nlink != 1
                or signature(before) != signature(current)
                or expected_size is not None and before.st_size != expected_size):
            raise NativeInventoryRejected("reviewed native source identity or size differs")
        target_fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        created = True
        digest = hashlib.sha256()
        copied = 0
        while block := os.read(source_fd, 1 << 20):
            copied += len(block)
            if expected_size is not None and copied > expected_size:
                raise NativeInventoryRejected("reviewed native source grew during copy")
            digest.update(block)
            view = memoryview(block)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise NativeInventoryRejected("private native copy made no progress")
                view = view[written:]
        os.fchmod(target_fd, mode)
        os.fsync(target_fd)
        after = os.fstat(source_fd)
        current = source.stat(follow_symlinks=False)
        if (copied != before.st_size or signature(before) != signature(after)
                or signature(before) != signature(current)
                or digest.hexdigest() != expected_sha256):
            raise NativeInventoryRejected("reviewed native source changed during copy")
        # A mutable source can be atomically replaced after the initial path
        # check while the original descriptor still points at the old inode.
        # Reopen the authorized pathname and hash the current object before
        # accepting the private copy; descriptor-only checks cannot see this.
        verify_fd = os.open(
            source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
        try:
            verify_info = os.fstat(verify_fd)
            verify_digest = hashlib.sha256()
            verify_size = 0
            while block := os.read(verify_fd, 1 << 20):
                verify_size += len(block)
                verify_digest.update(block)
            verify_current = source.stat(follow_symlinks=False)
            if (
                signature(verify_info) != signature(verify_current)
                or signature(verify_info) != signature(before)
                or verify_size != before.st_size
                or verify_digest.hexdigest() != expected_sha256
            ):
                raise NativeInventoryRejected("reviewed native source path changed during copy")
        finally:
            os.close(verify_fd)
    except BaseException:
        if target_fd is not None:
            os.close(target_fd)
            target_fd = None
        if created:
            target.unlink(missing_ok=True)
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(source_fd)

    try:
        copy_fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            copied_info = os.fstat(copy_fd)
            copied_digest = hashlib.sha256()
            while block := os.read(copy_fd, 1 << 20):
                copied_digest.update(block)
            final_info = os.fstat(copy_fd)
            current_copy = target.stat(follow_symlinks=False)
            if (signature(copied_info) != signature(final_info)
                    or signature(final_info) != signature(current_copy)
                    or copied_digest.hexdigest() != expected_sha256
                    or stat.S_IMODE(final_info.st_mode) != mode
                    or final_info.st_uid != os.geteuid()
                    or final_info.st_nlink != 1):
                raise NativeInventoryRejected("private native copy failed independent readback")
        finally:
            os.close(copy_fd)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {
        "source_path_sha256": _sha(str(source).encode()),
        "source_mode": stat.S_IMODE(before.st_mode),
        "source_size": before.st_size,
        "source_sha256": expected_sha256,
        "private_mode": mode,
        "private_size": final_info.st_size,
        "private_sha256": copied_digest.hexdigest(),
    }


def _private_dirs(root: Path, *names: str) -> dict[str, Path]:
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    root.chmod(0o700)
    values = {name: root / name for name in names}
    for path in values.values():
        path.mkdir(mode=0o700)
    return values


def codex_no_model_driver(
    root: Path, native_source: Path, catalog_source: Path, source_checkout: Path,
    binding: BindingIdentity, check_current,
) -> tuple[CodexAppServerDriver, SystemdUserSupervisor, Path, Path, dict[str, Any]]:
    """Stage the pinned 0.153.2 binary and a missing-key, zero-turn profile."""
    paths = _private_dirs(root, "bin", "codex-home", "cwd", "home", "tmp", "ledger")
    executable = paths["bin"] / "codex"
    native_pin = _copy_pinned(native_source, executable,
                              expected_sha256=CODEX_SHA256, expected_size=CODEX_SIZE)
    catalog = paths["codex-home"] / "models.json"
    catalog_pin = _copy_pinned(catalog_source, catalog,
                               expected_sha256=CODEX_CATALOG_SHA256, mode=0o600)
    schema = source_checkout / "runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json"
    schema_sha = _sha(schema.read_bytes())
    config = paths["codex-home"] / "config.toml"
    config.write_text("\n".join((
        'model = "gpt-5.6-sol"',
        'model_reasoning_effort = "low"',
        'model_provider = "fixture-provider"',
        f'model_catalog_json = "{catalog}"',
        'approval_policy = "never"',
        'default_permissions = "achp-engineer"',
        'allow_login_shell = false',
        'web_search = "disabled"',
        '[features]',
        'multi_agent = false',
        'multi_agent_v2 = false',
        'shell_tool = false',
        'request_permissions_tool = false',
        'apps = false',
        'plugins = false',
        'recommended_plugins = false',
        '[permissions.achp-engineer.filesystem]',
        '":minimal" = "read"',
        f'"{paths["cwd"]}" = "read"',
        '[model_providers.fixture-provider]',
        'name = "P1 no-model inventory"',
        'base_url = "https://provider.example.invalid/v1"',
        'wire_api = "responses"',
        '[model_providers.fixture-provider.auth]',
        'command = "/usr/bin/cat"',
        f'args = ["{root / "missing-no-model-key"}"]',
        'timeout_ms = 5000',
    )) + "\n", encoding="utf-8")
    config.chmod(0o600)
    profile = LaunchProfile(
        str(executable), CODEX_SHA256, "0.153.2", str(schema), schema_sha,
        str(paths["cwd"]), str(paths["codex-home"]), _sha(config.read_bytes()),
        "achp-engineer",
        {"PATH": "/opt/acs/codex-sandbox/bin:/usr/bin:/bin",
         "HOME": str(paths["home"]), "TMPDIR": str(paths["tmp"]),
         "LANG": "C.UTF-8"},
        "gpt-5.6-sol",
    )
    profile.validate()
    supervisor = SystemdUserSupervisor(
        tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
        termination_timeout=10,
    )
    driver = CodexAppServerDriver(
        "native-inventory-codex-" + root.name, profile,
        DriverJournal(paths["ledger"] / "driver.sqlite"),
        identity=binding, check_current=check_current,
        supervisor=supervisor, rpc_timeout=15,
    )
    return driver, supervisor, executable, config, {
        "native": native_pin, "catalog": catalog_pin,
    }


def opencode_no_model_driver(
    root: Path, native_source: Path, source_checkout: Path,
    binding: BindingIdentity, check_current,
) -> tuple[OpenCodeNativeDriver, SystemdUserSupervisor, Path, Path, dict[str, Any]]:
    """Stage pinned 1.18.30 with deny-all selected Agent and no provider key."""
    paths = _private_dirs(
        root, "bin", "home", "config", "data", "state", "cache",
        "input", "tmp", "ledger",
    )
    executable = paths["bin"] / "opencode"
    native_pin = _copy_pinned(native_source, executable,
                              expected_sha256=OPENCODE_SHA256, expected_size=OPENCODE_SIZE)
    schema = source_checkout / "runtime_tests/schema-1.18.30/opencode-openapi.json"
    if _sha(schema.read_bytes()) != OPENCODE_SCHEMA_SHA256:
        raise NativeInventoryRejected("OpenCode reviewed schema differs")
    config_dir = paths["config"] / "opencode"
    config_dir.mkdir(mode=0o700)
    config = config_dir / "opencode.json"
    config.write_bytes(_canonical({
        "$schema": "https://opencode.ai/config.json",
        "permission": {"*": "deny", "task": "deny"},
        "default_agent": "p1-observer",
        "model": "fixture-provider/fixture-model",
        "agent": {"p1-observer": {
            "model": "fixture-provider/fixture-model",
            "permission": {"*": "deny", "task": "deny"},
        }},
        "plugin": [], "mcp": {},
    }))
    config.chmod(0o600)
    profile = OpenCodeLaunchProfile(
        str(executable), OPENCODE_SHA256, "1.18.30",
        str(schema), OPENCODE_SCHEMA_SHA256,
        str(paths["input"]), str(paths["home"]), str(paths["config"]),
        str(paths["data"]), str(paths["state"]), str(paths["cache"]),
        str(paths["tmp"]), _sha(config.read_bytes()),
        "p1-observer", "fixture-provider", "fixture-model",
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    profile.validate(fresh=True)
    supervisor = SystemdUserSupervisor(
        tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
        termination_timeout=10,
    )
    driver = OpenCodeNativeDriver(
        "native-inventory-opencode-" + root.name, profile,
        DriverJournal(paths["ledger"] / "driver.sqlite"),
        identity=binding, check_current=check_current,
        supervisor=supervisor, http_timeout=10,
    )
    return driver, supervisor, executable, config, {"native": native_pin}


def _operation(prefix: str, message_id: str, grant_ref: str) -> AuthorizedOperation:
    return AuthorizedOperation(
        prefix, prefix + ":command", message_id, grant_ref,
        datetime.now(UTC) + timedelta(seconds=120),
    )


def _stop_native(driver, supervisor, message_id: str, grant_ref: str,
                 label: str) -> dict[str, Any]:
    """Stop an owned no-model process and close its transport and user bus."""
    proof = None
    try:
        if driver.owned is not None and driver.owned.process.poll() is None:
            try:
                receipt = driver.terminate(
                    _operation(label + ":stop", message_id, grant_ref),
                )
                proof = receipt["supervisor_proof"]
            except Exception:
                # An uncertain Driver termination still has to stop its unit.
                if driver.owned.process.poll() is None:
                    supervisor.terminate_tree(driver.owned)
                raise
        if proof is None:
            raise NativeInventoryRejected("native process did not return a stop proof")
        if proof.get("verified") is not True or proof.get("remaining_pids") != []:
            raise NativeInventoryRejected("native process tree was not fully stopped")
        driver.detach_transport()
        return proof
    finally:
        supervisor.close()


def _current_authority(
    authority: DomainAuthority, observed: BindingIdentity, expected: BindingIdentity,
    operation: AuthorizedOperation, *, work_id: str, message_id: str,
    attempt_id: str, source_commit: str, allowed_driver_messages: tuple[str, str],
) -> None:
    if (observed != expected or operation.message_id not in allowed_driver_messages
            or operation.grant_ref != authority.context.grant_ref):
        raise NativeInventoryRejected("native inventory left the current Node/Grant binding")
    with authority._connect() as connection:
        work = connection.execute(
            "SELECT scope_id,agent_slot_id,source_baseline,execution_status FROM work_items "
            "WHERE tenant_id=%s AND work_item_id=%s",
            (authority.tenant_id, work_id),
        ).fetchone()
        attempt = connection.execute(
            "SELECT status FROM delivery_attempts WHERE tenant_id=%s "
            "AND message_id=%s AND attempt_id=%s",
            (authority.tenant_id, message_id, attempt_id),
        ).fetchone()
        slot = connection.execute(
            "SELECT status FROM agent_slots WHERE tenant_id=%s AND scope_id='local-scope' "
            "AND agent_slot_id='local-slot'",
            (authority.tenant_id,),
        ).fetchone()
        scope = connection.execute(
            "SELECT status FROM scopes WHERE tenant_id=%s AND scope_id='local-scope'",
            (authority.tenant_id,),
        ).fetchone()
        grant = connection.execute(
            "SELECT revoked_at,expires_at,clock_timestamp() FROM grants "
            "WHERE tenant_id=%s AND grant_ref=%s",
            (authority.tenant_id, operation.grant_ref),
        ).fetchone()
    if (work != ("local-scope", "local-slot", source_commit, "ready")
            or attempt != ("delivered",) or slot != ("active",)
            or scope != ("active",) or grant is None
            or grant[0] is not None or grant[1] <= grant[2]):
        raise NativeInventoryRejected("native inventory current Work/Slot/Scope/Grant changed")


def _host_current_negatives(
    authority: DomainAuthority, service: Any, endpoint: Any, ledger_root: Path,
    *, run_id: str, message_id: str, command_id: str,
    operation_id: str, source_commit: str,
    native_path: Path, config_path: Path, native_sha256: str,
    config_sha256: str, driver: Any, host_class: type,
) -> dict[str, Any]:
    """The actual HostNode PG fence must reject a stale Slot and Policy."""
    with authority._connect() as connection:
        scope_policy = connection.execute(
            "SELECT policy FROM scopes WHERE tenant_id=%s AND scope_id='local-scope'",
            (authority.tenant_id,),
        ).fetchone()[0]
        attempts_before = connection.execute(
            "SELECT count(*) FROM delivery_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchone()[0]
    receipts_before = endpoint.journal.receipts(operation_id)
    policy = CodexHostRunPolicy(
        run_id=run_id,
        tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        scope_id="local-scope", agent_slot_id="local-slot",
        scope_policy_sha256=_sha(_canonical(scope_policy)),
        endpoint_id=next(key for key, value in service.endpoints.items() if value is endpoint),
        source_commit=source_commit,
        native_sha256=native_sha256, config_sha256=config_sha256,
        deadline=datetime.now(UTC) + timedelta(seconds=120),
    )
    endpoint.driver = NativeDeliveryAdapter(
        driver, authorize_invocation=lambda _invocation, _binding: None,
    )
    host = host_class(
        policy, DeliveryDispatcher(service), ledger_root / (driver.binding_id + "-host.sqlite"),
        native_path=native_path, config_path=config_path,
    )
    request = CodexHostRequest(
        action="dispatch", run_id=run_id,
        tenant_id=authority.tenant_id, message_id=message_id,
        command_id=command_id, operation_id=operation_id,
        endpoint_id=policy.endpoint_id, source_commit=source_commit,
        native_sha256=native_sha256, config_sha256=config_sha256,
    )
    spawn = AuthorizedOperation(
        run_id + "-spawn", run_id + "-command-spawn",
        run_id + "-message-spawn", authority.context.grant_ref,
        policy.deadline,
    )
    host._preflight(request)
    with host._spawn_authority_fence(request, spawn):
        pass  # Positive current check only; no second native spawn is authorized.
    reject_host_enablement_request()
    for model in (CodexHostRequest, OpenCodeHostRequest):
        body = request.model_dump()
        if model is OpenCodeHostRequest:
            body["schema_version"] = "acs-p1-opencode-host-request/1"
        try:
            model.model_validate({**body, "native_delegation_enabled": True}, strict=True)
        except ValueError as exc:
            if "native_delegation_enabled" not in str(exc):
                raise NativeInventoryRejected("HostNode rejected a different field") from exc
        else:
            raise NativeInventoryRejected("HostNode admitted native delegation override")
    rejected = []
    for kind, statement, params in (
        ("slot", ("UPDATE agent_slots SET status='revoked' "
                  "WHERE tenant_id=%s AND agent_slot_id='local-slot'"),
         (authority.tenant_id,)),
        ("policy", ("UPDATE scopes SET policy=%s "
                    "WHERE tenant_id=%s AND scope_id='local-scope'"),
         (json.dumps({"native_delegation": "attempted"}), authority.tenant_id)),
    ):
        with authority._connect() as connection:
            connection.execute(statement, params)
        try:
            try:
                host.start_native(request, spawn)
            except HostNodeRejected as exc:
                if "WorkItem/AgentSlot/Policy is not current" not in str(exc):
                    raise NativeInventoryRejected(
                        "HostNode rejected an unrelated native launch condition"
                    ) from exc
                rejected.append(kind)
            else:
                raise NativeInventoryRejected("HostNode admitted a changed Slot or Policy")
        finally:
            with authority._connect() as connection:
                if kind == "slot":
                    connection.execute(
                        "UPDATE agent_slots SET status='active' WHERE tenant_id=%s "
                        "AND agent_slot_id='local-slot'", (authority.tenant_id,),
                    )
                else:
                    connection.execute(
                        "UPDATE scopes SET policy=%s WHERE tenant_id=%s "
                        "AND scope_id='local-scope'",
                        (json.dumps(scope_policy), authority.tenant_id),
                    )
    with authority._connect() as connection:
        attempts_after = connection.execute(
            "SELECT count(*) FROM delivery_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchone()[0]
    with sqlite3.connect(host.ledger_path) as connection:
        host_rows = tuple(connection.execute(
            query,
        ).fetchone()[0] for query in (
            "SELECT count(*) FROM codex_host_runs",
            "SELECT count(*) FROM codex_host_boot",
        ))
    if (rejected != ["slot", "policy"] or attempts_after != attempts_before
            or endpoint.journal.receipts(operation_id) != receipts_before
            or host_rows != (0, 0)):
        raise NativeInventoryRejected("HostNode denial altered delivery attempts")
    return {
        "host_policy_sha256": policy.scope_policy_sha256,
        "slot_and_policy_rejected": True,
        "attempt_count_unchanged": True,
        "node_receipts_unchanged": True,
        "host_ledger_rows": [0, 0],
        "host_ledger": host.ledger_path.name,
    }


def run(
    authority: DomainAuthority, node: NodeJournal, endpoint: Any, service: Any,
    ledger: Any, work_id: str, message_id: str, operation_id: str,
    source_commit: str, source_tree: str, suffix: str,
    source_checkout: Path, private_json,
) -> dict[str, Any]:
    """Boot actual pinned native servers without a model request; retain gap."""
    proof_path = ledger.root / (SCENARIO + "-proof.json")
    if proof_path.exists():
        previous = json.loads(proof_path.read_text())
        if (previous.get("message_id") != message_id
                or previous.get("operation_id") != operation_id):
            raise NativeInventoryRejected("native inventory proof belongs to another message")
        return previous
    paths = {
        "codex": os.environ.get("ACS_P1_CODEX_NATIVE_PATH"),
        "catalog": os.environ.get("ACS_P1_CODEX_CATALOG_PATH"),
        "opencode": os.environ.get("ACS_P1_OPENCODE_NATIVE_PATH"),
    }
    if any(not value or not Path(value).is_absolute() for value in paths.values()):
        raise NativeInventoryRejected("reviewed no-model native source paths are unavailable")
    with authority._connect() as connection:
        attempt_rows = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal", (message_id,),
        ).fetchall()
        command = connection.execute(
            "SELECT command_id,command_json->>'correlation_id' "
            "FROM delivery_messages WHERE message_id=%s", (message_id,),
        ).fetchone()
    run_id = "p1-native-" + suffix
    if (len(attempt_rows) != 1 or attempt_rows[0][2] != "delivered"
            or command is None or command[1] != run_id):
        raise NativeInventoryRejected("native inventory lacks one committed run Attempt")
    attempt_id, dispatch_id, _ = attempt_rows[0]
    native_root = ledger.root / (SCENARIO + "-native")
    native_root.mkdir(mode=0o700)
    summaries = {}
    terminations = {}
    hosts = {}
    source_pins = {}
    for kind in ("codex", "opencode"):
        binding = BindingIdentity(
            node.node_id, node.boot_incarnation,
            "p1-native-" + kind + "-runtime-" + suffix,
            attempt_id, "local-slot", 1,
        )
        bootstrap_message = message_id + ":" + kind + ":bootstrap"
        stop_message = message_id + ":" + kind + ":stop"

        def current(
            operation, observed, expected=binding,
            allowed=(bootstrap_message, stop_message),
        ):
            _current_authority(
                authority, observed, expected, operation,
                work_id=work_id, message_id=message_id,
                attempt_id=attempt_id, source_commit=source_commit,
                allowed_driver_messages=allowed,
            )

        root = native_root / kind
        if kind == "codex":
            driver, supervisor, executable, config, pins = codex_no_model_driver(
                root, Path(paths["codex"]), Path(paths["catalog"]),
                source_checkout, binding, current,
            )
        else:
            driver, supervisor, executable, config, pins = opencode_no_model_driver(
                root, Path(paths["opencode"]), source_checkout,
                binding, current,
            )
        try:
            operation = _operation(
                run_id + "-" + kind + "-bootstrap", bootstrap_message,
                authority.context.grant_ref,
            )
            if kind == "codex":
                summary = capture_codex_bootstrap(driver, operation)
            else:
                summary = capture_opencode_bootstrap(driver, operation)
            witness = summary.pop("_witness")
            summary["inventory_witness_sha256"] = _sha(private_json(
                root / "inventory.json", witness,
            ))
            host_denial = _host_current_negatives(
                authority, service, endpoint, root,
                run_id=run_id, message_id=message_id,
                command_id=command[0], operation_id=operation_id,
                source_commit=source_commit, native_path=executable,
                config_path=config, native_sha256=summary["native_executable_sha256"],
                config_sha256=summary["config_sha256"], driver=driver,
                host_class=(CodexHostNodeEndpoint if kind == "codex"
                            else OpenCodeHostNodeEndpoint),
            )
            termination = _stop_native(
                driver, supervisor, stop_message, authority.context.grant_ref,
                run_id + "-" + kind,
            )
        except BaseException:
            if driver.owned is not None and driver.owned.process.poll() is None:
                supervisor.terminate_tree(driver.owned)
            supervisor.close()
            raise
        summaries[kind] = summary
        source_pins[kind] = pins
        terminations[kind] = {
            "verified": termination["verified"],
            "remaining_pids": termination["remaining_pids"],
            "containment_id": termination["containment_id"],
            "root_exited": termination["root_exited"],
            "main_pid": termination["main_pid"],
            "unit": termination["unit"],
            "active_state": termination["active_state"],
        }
        hosts[kind] = host_denial
        with node._transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS p1_native_inventory("
                "kind TEXT PRIMARY KEY,message_id TEXT NOT NULL,attempt_id TEXT NOT NULL,"
                "operation_id TEXT NOT NULL,summary_sha256 TEXT NOT NULL,"
                "termination_sha256 TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO p1_native_inventory VALUES (?,?,?,?,?,?)",
                (kind, message_id, attempt_id, operation_id,
                 _sha(_canonical(summary)), _sha(_canonical(terminations[kind]))),
            )
    if (summaries["codex"].get("model_turn_count") != 0
            or summaries["opencode"].get("model_prompt_count") != 0):
        raise NativeInventoryRejected("no-model native inventory made a model request")
    proof = {
        "work_item_id": work_id, "message_id": message_id,
        "operation_id": operation_id, "attempt_id": attempt_id,
        "dispatch_id": dispatch_id, "source_commit": source_commit,
        "source_tree": source_tree, "node_id": node.node_id,
        "machine_id": node.machine_id, "run_id": run_id,
        "summaries": summaries, "terminations": terminations,
        "source_pins": source_pins,
        "host_denials": hosts, "model_request_count": 0,
        "formal_request_behavior_measured": False,
    }
    private_json(proof_path, proof)
    return proof


def read_layer(
    profile: dict[str, Any], kind: str, ledger: Any,
    row: dict[str, Any], lineage: dict[str, Any],
) -> dict[str, Any]:
    proof = lineage.get("native_multiagent_proof")
    if not isinstance(proof, dict):
        raise NativeInventoryRejected("native delegation inventory proof is missing")
    proof_path = ledger.root / (SCENARIO + "-proof.json")
    try:
        raw = proof_path.read_bytes()
        stored = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise NativeInventoryRejected("native delegation inventory proof is unreadable") from exc
    if (stored != proof or raw != _canonical(proof)
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("operation_id") != lineage["operation_id"]
            or proof.get("attempt_id") != lineage["attempt_id"]
            or proof.get("dispatch_id") != lineage["dispatch_id"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("model_request_count") != 0
            or proof.get("formal_request_behavior_measured") is not False
            or set(proof.get("summaries", {})) != {"codex", "opencode"}
            or set(proof.get("host_denials", {})) != {"codex", "opencode"}
            or any(not item.get("slot_and_policy_rejected")
                   for item in proof["host_denials"].values())
            or any(not item.get("verified") or item.get("remaining_pids") != []
                   for item in proof.get("terminations", {}).values())):
        raise NativeInventoryRejected("native delegation inventory differs from Runtime lineage")
    if kind == "postgresql":
        scoped = make_conninfo(
            profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
        )
        with psycopg.connect(scoped) as connection:
            work = connection.execute(
                "SELECT scope_id,agent_slot_id,source_baseline,state,revision "
                "FROM work_items WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()
            message = connection.execute(
                "SELECT operation_id,command_json->>'correlation_id' "
                "FROM delivery_messages WHERE message_id=%s",
                (proof["message_id"],),
            ).fetchone()
            attempts = connection.execute(
                "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
                "WHERE message_id=%s ORDER BY ordinal",
                (proof["message_id"],),
            ).fetchall()
            slot = connection.execute(
                "SELECT status FROM agent_slots WHERE agent_slot_id='local-slot'",
            ).fetchone()
            scope = connection.execute(
                "SELECT status,policy FROM scopes WHERE scope_id='local-scope'",
            ).fetchone()
            accepted = connection.execute(
                "SELECT count(*) FROM accepted_state_revisions WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()[0]
        if (work != ("local-scope", "local-slot", row["source_commit"], "candidate", 0)
                or message != (proof["operation_id"], proof["run_id"])
                or attempts != [(proof["attempt_id"], proof["dispatch_id"], "delivered")]
                or slot != ("active",) or scope is None or scope[0] != "active"
                or any(item["host_policy_sha256"] != _sha(_canonical(scope[1]))
                       for item in proof["host_denials"].values())
                or accepted != 0):
            raise NativeInventoryRejected("PostgreSQL native delegation lineage changed")
        return {"current_policy_slot_readback": True, "attempt_count": 1,
                "accepted_unchanged": True}
    if kind == "sqlite":
        node_path = ledger.root / lineage["node_journal"]
        with sqlite3.connect(node_path) as connection:
            observed = connection.execute(
                "SELECT kind,message_id,attempt_id,operation_id,summary_sha256,"
                "termination_sha256 FROM p1_native_inventory ORDER BY kind",
            ).fetchall()
        expected = [(
            native, proof["message_id"], proof["attempt_id"], proof["operation_id"],
            _sha(_canonical(proof["summaries"][native])),
            _sha(_canonical(proof["terminations"][native])),
        ) for native in ("codex", "opencode")]
        if observed != expected:
            raise NativeInventoryRejected("Node native inventory observation changed")
        native_root = ledger.root / (SCENARIO + "-native")
        for native in ("codex", "opencode"):
            host_path = native_root / native / proof["host_denials"][native]["host_ledger"]
            with sqlite3.connect(host_path) as connection:
                host_rows = tuple(connection.execute(
                    query,
                ).fetchone()[0] for query in (
                    "SELECT count(*) FROM codex_host_runs",
                    "SELECT count(*) FROM codex_host_boot",
                ))
            if host_rows != (0, 0):
                raise NativeInventoryRejected("HostNode denial left a launch claim")
        return {"node_inventory_count": 2, "node_inventory_bound": True}
    if kind == "driver":
        native_root = ledger.root / (SCENARIO + "-native")
        for native in ("codex", "opencode"):
            root = native_root / native
            witness_path = root / "inventory.json"
            info = witness_path.stat(follow_symlinks=False)
            raw_witness = witness_path.read_bytes()
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or _sha(raw_witness) != proof["summaries"][native]["inventory_witness_sha256"]):
                raise NativeInventoryRejected("actual native inventory witness identity changed")
            witness = json.loads(raw_witness)
            summary = proof["summaries"][native]
            if native == "codex":
                current = codex_effective_inventory(
                    (root / "codex-home/config.toml").read_bytes(),
                    witness["active_settings"], witness["feature_reads"],
                    permission_profile="achp-engineer", cwd=str(root / "cwd"),
                )
                keys = ("config_sha256", "effective_features_sha256",
                        "effective_feature_count", "multi_agent", "multi_agent_v2")
            else:
                from types import SimpleNamespace
                current = opencode_effective_inventory(
                    witness["config"], witness["agents"], witness["tool_ids"],
                    profile=SimpleNamespace(
                        agent="p1-observer", data_root=str(root / "data"),
                        temp_root=str(root / "tmp"),
                    ),
                )
                keys = ("effective_permission_sha256", "effective_agents_sha256",
                        "effective_agent_count", "effective_rules_sha256",
                        "effective_tool_ids_sha256", "effective_tool_count",
                        "task_tool_present_but_denied")
            if any(current[key] != summary[key] for key in keys):
                raise NativeInventoryRejected("actual effective native inventory changed")
            with sqlite3.connect(root / "ledger/driver.sqlite") as connection:
                spawned = connection.execute(
                    "SELECT count(*) FROM driver_events WHERE kind='process_started'",
                ).fetchone()[0]
                native_calls = connection.execute(
                    "SELECT count(*) FROM driver_events WHERE kind=? AND body LIKE ?",
                    ("rpc_dispatch" if native == "codex" else "http_dispatch",
                     "%turn/start%" if native == "codex" else "%prompt_async%"),
                ).fetchone()[0]
            if spawned != 1 or native_calls != 0:
                raise NativeInventoryRejected("native Driver journal has a model request")
        return {"native_config_and_inventory_rechecked": True,
                "model_request_count": 0}
    if kind == "os":
        native_root = ledger.root / (SCENARIO + "-native")
        for native in ("codex", "opencode"):
            root = native_root / native
            executable = root / "bin" / native
            config = (root / "codex-home/config.toml" if native == "codex"
                      else root / "config/opencode/opencode.json")
            expected = proof["summaries"][native]
            if (_sha256_owner_file(executable, executable=True)
                    != expected["native_executable_sha256"]
                    or _sha256_owner_file(config, executable=False)
                    != expected["config_sha256"]):
                raise NativeInventoryRejected("staged native binary or config changed")
            stopped = proof["terminations"][native]
            if stopped["active_state"] not in ("inactive", "failed"):
                raise NativeInventoryRejected("native process survived termination")
            uid = os.geteuid()
            systemd = subprocess.run(
                ["/usr/bin/systemctl", "--user", "show", stopped["unit"],
                 "--property=ActiveState", "--value"],
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                     "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                     "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"},
                capture_output=True, text=True, timeout=10, check=False,
            )
            if systemd.returncode != 0 or systemd.stdout.strip() in (
                "active", "activating", "reloading",
            ):
                raise NativeInventoryRejected("native Systemd unit remains active")
        return {"native_processes_stopped": True, "remaining_pids": []}
    return {"native_inventory_proof_readback": True}
