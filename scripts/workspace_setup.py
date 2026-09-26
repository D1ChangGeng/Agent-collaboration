#!/usr/bin/env python3
"""Fail-closed Project Collaboration Workspace and Route operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_KIND = "project-collaboration-root"
SCHEMA = "0.2"
STATES = {"discovered", "active", "paused", "completed", "archived", "legacy-unmigrated"}
DEFAULT_REGISTRY_PATH = ".agents/coordination/routes.yaml"
DEFAULT_BASELINE_PATH = ".agents/coordination/ROOT-BASELINE.md"
DEFAULT_SOURCE_STATE_PATH = ".agents/protocol/SOURCE-STATE.md"

WORKSPACE_ASSETS = {
    ".agents/README.md": "workspace/.agents/README.md",
    ".agents/protocol/CAPABILITIES.md": "workspace/.agents/protocol/CAPABILITIES.md",
    ".agents/protocol/RELAY.md": "workspace/.agents/protocol/RELAY.md",
    ".agents/protocol/GIT-SYNC.md": "workspace/.agents/protocol/GIT-SYNC.md",
    ".agents/protocol/KNOWLEDGE.md": "workspace/.agents/protocol/KNOWLEDGE.md",
    ".agents/protocol/SOURCE-STATE.md": "workspace/.agents/protocol/SOURCE-STATE.md",
    ".agents/coordination/ROOT.md": "workspace/.agents/coordination/ROOT.md",
    ".agents/coordination/ROOT-BASELINE.md": "workspace/.agents/coordination/ROOT-BASELINE.md",
    ".agents/coordination/PROJECT.md": "workspace/.agents/coordination/PROJECT.md",
    ".agents/coordination/handoffs/.gitkeep": "workspace/.agents/coordination/handoffs/.gitkeep",
    ".agents/knowledge/README.md": "workspace/.agents/knowledge/README.md",
}
PROJECT_OWNED = {".agents/coordination/ROOT-BASELINE.md", ".agents/coordination/PROJECT.md"}
WORKSPACE_CREATE = [
    ".agents/config.yaml",
    ".agents/settings.yaml",
    ".agents/knowledge/index.yaml",
    ".agents/knowledge/guides/.gitkeep",
    ".agents/knowledge/decisions/.gitkeep",
    ".agents/knowledge/observations/.gitkeep",
    ".agents/knowledge/archive/.gitkeep",
    ".agents/runtime/.gitkeep",
]
AGENTS_BEGIN = "<!-- ACHP-WORKSPACE:BEGIN -->"
AGENTS_END = "<!-- ACHP-WORKSPACE:END -->"
CLAUDE_BEGIN = "<!-- ACHP-CLAUDE-ROUTER:BEGIN -->"
CLAUDE_END = "<!-- ACHP-CLAUDE-ROUTER:END -->"
GITIGNORE_BEGIN = "# ACHP-WORKSPACE:BEGIN"
GITIGNORE_END = "# ACHP-WORKSPACE:END"


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _asset(rel: str) -> str:
    return (_skill_root() / "assets" / "scaffold" / rel).read_text(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def read_json(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        # Registry/manifest files deliberately use JSON, which is also valid
        # YAML 1.2.  Keeping the parser in the Python standard library avoids
        # an optional YAML dependency and gives deterministic fail-closed input
        # handling across supported hosts.
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON-compatible YAML at {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected object at {path}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(path: Path) -> Path:
    return path.expanduser().resolve()


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_path(root: Path, relative: Any) -> Optional[Path]:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    # Paths in the manifest are durable pointers.  Reject aliases such as
    # ``./routes.yaml`` and ``foo/../routes.yaml`` instead of silently
    # normalising them into a second spelling of the same source of truth.
    raw = relative.replace("\\", "/")
    if any(part in {"", ".", ".."} for part in raw.split("/")):
        return None
    candidate = (root / relative).resolve()
    if not _contained(root, candidate):
        return None
    try:
        canonical = candidate.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return candidate if raw == canonical else None


def _canonical_route(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"invalid route path: {relative!r}")
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not _contained(root, candidate):
        raise ValueError(f"route path escapes workspace: {relative}")
    if candidate == root:
        raise ValueError("route path points to workspace root")
    control = (root / ".agents").resolve()
    if candidate == control or control in candidate.parents:
        raise ValueError(f"route path uses workspace control directory: {relative}")
    canonical = candidate.relative_to(root).as_posix()
    if Path(relative).as_posix() != canonical:
        raise ValueError(f"route path is not canonical: {relative}")
    return candidate


def _route_pointer(route: Path, target: Path) -> str:
    return Path(os.path.relpath(str(target), str(route))).as_posix()


def _replace_block(text: str, begin: str, end: str, block: str) -> str:
    block = block.strip() + "\n"
    if begin in text and end in text:
        left, rest = text.split(begin, 1)
        _, right = rest.split(end, 1)
        result = left.rstrip() + ("\n\n" if left.strip() else "") + block
        if right.strip():
            result += "\n" + right.lstrip()
        return result
    return (text.rstrip() + "\n\n" if text.strip() else "") + block


def _extract_block(text: str, begin: str, end: str) -> Optional[str]:
    if begin not in text or end not in text:
        return None
    _, rest = text.split(begin, 1)
    body, _ = rest.split(end, 1)
    return body.strip()


def _write(path: Path, content: str, dry_run: bool, actions: List[str]) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(f"target is a directory, expected a file: {path}")
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    actions.append(f"write {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "route"


def route_id(path: Path, display: Optional[str] = None) -> str:
    candidate = _slug(display or path.name)
    return candidate if candidate != "route" else "route-" + hashlib.sha1(str(path).encode()).hexdigest()[:8]


def validate_manifest(data: Dict[str, Any], root: Optional[Path] = None) -> None:
    if data.get("kind") != WORKSPACE_KIND:
        raise ValueError(f"workspace manifest kind invalid: {data.get('kind')!r}")
    if data.get("management_root") is not True:
        raise ValueError("workspace manifest management_root must be true")
    if data.get("execution_repository_required") is not False:
        raise ValueError("workspace manifest execution_repository_required must be false")
    if data.get("runtime_dependency_on_setup_skill") is not False:
        raise ValueError("workspace manifest runtime dependency must be false")
    if not isinstance(data.get("root_id"), str) or not data.get("root_id"):
        raise ValueError("workspace manifest root_id must be a non-empty string")
    if data.get("setup_skill") != "agent-collaboration-setup":
        raise ValueError("workspace manifest setup_skill is invalid")
    for key in ("registry_path", "baseline_path", "source_state_path"):
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"workspace manifest {key} must be a relative path")
        if root is not None and _safe_path(root, value) is None:
            raise ValueError(f"workspace manifest {key} escapes workspace")
    # Baseline and source-state pointers are part of the Root contract and are
    # referenced by generated Root/Route instructions.  They are intentionally
    # canonical in schema 0.2; allowing an arbitrary alternate spelling here
    # would create a dangling pointer or a second source of truth.
    if data.get("baseline_path") != DEFAULT_BASELINE_PATH:
        raise ValueError(f"workspace manifest baseline_path must be {DEFAULT_BASELINE_PATH}")
    if data.get("source_state_path") != DEFAULT_SOURCE_STATE_PATH:
        raise ValueError(f"workspace manifest source_state_path must be {DEFAULT_SOURCE_STATE_PATH}")
    for key in ("managed_files", "project_owned_files"):
        values = data.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError(f"workspace manifest {key} must be a list of relative paths")
        if root is not None:
            for value in values:
                if _safe_path(root, value) is None:
                    raise ValueError(f"workspace manifest {key} contains an unsafe path: {value}")
    hashes = data.get("managed_hashes", {})
    if not isinstance(hashes, dict) or any(
        not isinstance(k, str)
        or not isinstance(v, str)
        or not re.fullmatch(r"[0-9a-f]{64}", v)
        for k, v in hashes.items()
    ):
        raise ValueError("workspace manifest managed_hashes must map strings to strings")
    if root is not None:
        for key in hashes:
            if _safe_path(root, key) is None:
                raise ValueError(f"workspace manifest managed hash path is unsafe: {key}")


def validate_registry(data: Dict[str, Any], root: Path, expected_root_id: str = "agent-collaboration-root") -> None:
    if data.get("root_id") != expected_root_id:
        raise ValueError("routes registry root_id is invalid")
    if not isinstance(data.get("schema_version"), str) or not data.get("schema_version"):
        raise ValueError("routes registry schema_version is invalid")
    routes = data.get("routes")
    if not isinstance(routes, list):
        raise ValueError("routes registry must contain a list")
    ids: set[str] = set()
    paths: set[str] = set()
    canonical: set[str] = set()

    def validate_pointer(value: Any, field: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid route {field}")
        if value in {"unknown", "unverified", "not-measured"}:
            return
        if _safe_path(root, value) is None:
            raise ValueError(f"route {field} escapes workspace")

    def validate_status_object(value: Any, field: str) -> None:
        if not isinstance(value, dict):
            raise ValueError(f"route {field} must be an object")
        status = value.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError(f"route {field}.status must be a non-empty string")

    for entry in routes:
        if not isinstance(entry, dict):
            raise ValueError("routes registry contains a non-object entry")
        rid, rel = entry.get("id"), entry.get("path")
        if not isinstance(rid, str) or not rid:
            raise ValueError(f"invalid route id: {rid!r}")
        if not isinstance(rel, str) or not rel:
            raise ValueError(f"invalid route path: {rel!r}")
        if rid in ids or rel in paths:
            raise ValueError(f"duplicate route id/path: {rid} / {rel}")
        target = _canonical_route(root, rel)
        if str(target) in canonical:
            raise ValueError(f"duplicate canonical route path: {rel}")
        if not target.is_dir():
            raise ValueError(f"route directory missing: {rel}")
        if not isinstance(entry.get("display_name"), str) or not entry.get("display_name"):
            raise ValueError(f"invalid route display_name for {rid}")
        if entry.get("status") not in STATES:
            raise ValueError(f"invalid route state for {rid}")
        for field in ("agents_path", "knowledge_root", "knowledge_index", "work_scope"):
            if field not in entry:
                raise ValueError(f"route {field} is required for {rid}")
            validate_pointer(entry[field], field)
        for field in ("migration_status", "migration_contract", "knowledge_index_status"):
            if field not in entry or not isinstance(entry[field], str) or not entry[field]:
                raise ValueError(f"route {field} must be a non-empty string")
        validate_status_object(entry.get("source_repository"), "source_repository")
        validate_status_object(entry.get("execution_endpoints"), "execution_endpoints")
        evidence = entry.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("route evidence must be an object")
        for field, value in evidence.items():
            if not isinstance(value, str):
                raise ValueError(f"route evidence.{field} must be a string")
        ids.add(rid)
        paths.add(rel)
        canonical.add(str(target))


def _discover(workspace: Path) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    used: set[str] = set()
    if not workspace.exists():
        return result
    for child in sorted(workspace.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not ((child / "AGENTS.md").exists() or (child / ".agents").exists()):
            continue
        rel = child.relative_to(workspace).as_posix()
        rid = route_id(child)
        if rid in used:
            rid += "-" + hashlib.sha1(rel.encode()).hexdigest()[:8]
        used.add(rid)
        route_meta = child / ".agents" / "route.yaml"
        existing_meta: Optional[Dict[str, Any]] = None
        if route_meta.exists():
            existing_meta = read_json(route_meta)
            validate_route_metadata(existing_meta, child, workspace)
            rid = existing_meta["route_id"]
        scope = next((f"{rel}/{name}" for name in ("Improve", "Implement") if (child / name).is_dir()), "unknown")
        result.append({
            "id": rid,
            "display_name": existing_meta.get("display_name", child.name) if existing_meta else child.name,
            "path": rel,
            "work_scope": scope,
            "status": existing_meta.get("state", "discovered") if existing_meta else "discovered",
            "migration_status": "legacy-unmigrated",
            "agents_path": f"{rel}/AGENTS.md" if (child / "AGENTS.md").exists() else "unknown",
            "knowledge_root": f"{rel}/.agents/knowledge" if (child / ".agents/knowledge").exists() else "unknown",
            "knowledge_index": f"{rel}/.agents/knowledge/index.yaml" if (child / ".agents/knowledge/index.yaml").exists() else "unknown",
            "knowledge_index_status": "present_with_observations" if (child / ".agents/knowledge/observations").exists() and any((child / ".agents/knowledge/observations").glob("*.md")) else "present",
            "source_repository": {"status": "unknown"},
            "execution_endpoints": {"status": "unknown"},
            "migration_contract": "0.2-required",
            "evidence": {"path": "local-verified", "execution": "unknown"},
        })
    return result


def _merge_registry(existing: Dict[str, Any], discovered: List[Dict[str, Any]]) -> Dict[str, Any]:
    current = {entry["path"]: entry for entry in existing.get("routes", [])}
    result = dict(existing)
    result["schema_version"] = SCHEMA
    result["routes"] = []
    for item in discovered:
        old = current.get(item["path"])
        merged = dict(item)
        if old:
            merged.update(old)
            merged["path"] = item["path"]
            merged["display_name"] = old.get("display_name", item["display_name"])
        result["routes"].append(merged)
    seen = {item["path"] for item in discovered}
    result["routes"].extend(item for item in existing.get("routes", []) if item.get("path") not in seen)
    result["routes"].sort(key=lambda item: str(item.get("id", item.get("path", ""))))
    return result


def _workspace_manifest(root: Path, old: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    old = old or {}
    registry_path = old.get("registry_path", DEFAULT_REGISTRY_PATH)
    if _safe_path(root, registry_path) is None:
        registry_path = DEFAULT_REGISTRY_PATH
    default_managed = sorted(rel for rel in WORKSPACE_ASSETS if rel not in PROJECT_OWNED)
    default_owned = [
        ".agents/coordination/ROOT-BASELINE.md",
        ".agents/coordination/PROJECT.md",
        registry_path,
    ]
    managed_files = old.get("managed_files", default_managed)
    project_owned_files = old.get("project_owned_files", default_owned)
    if not isinstance(managed_files, list) or any(not isinstance(value, str) for value in managed_files):
        managed_files = default_managed
    if not isinstance(project_owned_files, list) or any(not isinstance(value, str) for value in project_owned_files):
        project_owned_files = default_owned
    return {
        "schema_version": SCHEMA,
        "kind": WORKSPACE_KIND,
        "root_id": old.get("root_id", "agent-collaboration-root"),
        "root_path": str(root),
        "management_root": True,
        "execution_repository_required": False,
        "setup_skill": "agent-collaboration-setup",
        "runtime_dependency_on_setup_skill": False,
        "registry_path": registry_path,
        "baseline_path": DEFAULT_BASELINE_PATH,
        "source_state_path": DEFAULT_SOURCE_STATE_PATH,
        # Keep the managed surface explicit and deterministic. Older 0.2
        # manifests already carried these fields; retaining them makes
        # upgrades idempotent while giving ownership checks a stable inventory.
        "managed_files": managed_files,
        "preserved_route_paths": list(
            old.get("preserved_route_paths", [])
            if isinstance(old.get("preserved_route_paths", []), list)
            else []
        ),
        "project_owned_files": project_owned_files,
        "created_at": old.get("created_at", _now()),
        "managed_hashes": old.get("managed_hashes", {}),
    }


def _preflight_file_targets(root: Path, extra_paths: Optional[List[str]] = None) -> None:
    """Reject file/directory collisions before any workspace write."""
    targets = ["AGENTS.md", "CLAUDE.md", ".gitignore"] + list(WORKSPACE_ASSETS) + list(WORKSPACE_CREATE) + [".agents/manifest.json"]
    targets.extend(extra_paths or [])
    root = root.resolve()
    seen = set()
    for rel in targets:
        if rel in seen:
            continue
        seen.add(rel)
        if _safe_path(root, rel) is None:
            raise ValueError(f"target path is unsafe: {rel}")
        path = root / rel
        if path.exists() and not _contained(root, path.resolve()):
            raise ValueError(f"target path resolves outside workspace: {rel}")
        if path.exists() and path.is_dir():
            raise ValueError(f"target is a directory, expected a file: {path}")
        parent = path.parent
        while parent != root and _contained(root, parent):
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"target parent is a file, expected a directory: {parent}")
            parent = parent.parent


def _preflight_route_targets(workspace: Path, route: Path) -> None:
    """Reject route file/directory collisions before route writes."""
    workspace = workspace.resolve()
    route = route.resolve()
    if route.exists() and not route.is_dir():
        raise ValueError(f"route target is not a directory: {route}")
    if route.exists() and not _contained(workspace, route.resolve()):
        raise ValueError(f"route target resolves outside workspace: {route}")
    parent = route
    while parent != workspace and _contained(workspace, parent):
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"route parent is a file, expected a directory: {parent}")
        parent = parent.parent
    for rel in [
        "AGENTS.md",
        ".agents/route.yaml",
        ".agents/settings.yaml",
        ".agents/state/source-state.yaml",
        ".agents/knowledge/index.yaml",
        ".agents/knowledge/guides/.gitkeep",
        ".agents/knowledge/decisions/.gitkeep",
        ".agents/knowledge/observations/.gitkeep",
        ".agents/knowledge/archive/.gitkeep",
    ]:
        path = route / rel
        if path.exists() and not _contained(route, path.resolve()):
            raise ValueError(f"route target resolves outside route: {rel}")
        if path.exists() and path.is_dir():
            raise ValueError(f"route target is a directory, expected a file: {path}")
        parent = path.parent
        while parent != route and _contained(route, parent):
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"route target parent is a file, expected a directory: {parent}")
            parent = parent.parent


def validate_route_metadata(
    meta: Dict[str, Any],
    route: Path,
    workspace: Path,
    entry: Optional[Dict[str, Any]] = None,
    expected_root_id: str = "agent-collaboration-root",
) -> None:
    """Validate route metadata and its Root contract pointer."""
    if meta.get("kind") != "development-route":
        raise ValueError("route metadata kind invalid")
    if not isinstance(meta.get("route_id"), str) or not meta.get("route_id"):
        raise ValueError("route metadata route_id is invalid")
    if not isinstance(meta.get("display_name"), str) or not meta.get("display_name"):
        raise ValueError("route metadata display_name is invalid")
    if meta.get("root_id") != expected_root_id:
        raise ValueError("route metadata root_id is invalid")
    expected_path = route.relative_to(workspace).as_posix()
    if meta.get("path") != expected_path:
        raise ValueError("route metadata path does not match registry path")
    if meta.get("state") not in STATES:
        raise ValueError("route metadata state is invalid")
    expected_contract = _route_pointer(route, workspace / ".agents/coordination/ROOT-BASELINE.md")
    if meta.get("root_contract") != expected_contract:
        raise ValueError("route metadata Root contract pointer is invalid")
    if entry is not None:
        if meta.get("route_id") != entry.get("id"):
            raise ValueError("route metadata route_id does not match registry")
        if meta.get("display_name") != entry.get("display_name"):
            raise ValueError("route metadata display_name does not match registry")
        if meta.get("state") != entry.get("status"):
            raise ValueError("route metadata state does not match registry")


def _route_metadata_payload(route: Path, workspace: Path, rid: str, display: str, root_id: str, state: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "kind": "development-route",
        "route_id": rid,
        "display_name": display,
        "root_id": root_id,
        "path": route.relative_to(workspace).as_posix(),
        "state": state,
        "root_contract": _route_pointer(route, workspace / ".agents/coordination/ROOT-BASELINE.md"),
        "knowledge_scope": ".agents/knowledge/",
        "source_state_ref": ".agents/state/source-state.yaml",
        "source_repository": {"status": "unknown"},
        "execution_endpoints": {"status": "unknown", "items": []},
        "evidence": {"class": "local-verified", "source": "route metadata", "refresh_trigger": "source or endpoint identity changes"},
    }


def workspace_install(root: Path, mode: str, dry_run: bool) -> List[str]:
    actions: List[str] = []
    root = root.expanduser().resolve()
    if root.exists() and not root.is_dir():
        return [f"error workspace target is not a directory: {root}"]
    manifest_path = root / ".agents" / "manifest.json"
    old: Optional[Dict[str, Any]] = None
    if manifest_path.exists():
        try:
            old = read_json(manifest_path)
            validate_manifest(old, root)
        except (OSError, ValueError) as exc:
            return [f"error {manifest_path}: {exc}"]
    registry_path = _safe_path(root, (old or {}).get("registry_path", ".agents/coordination/routes.yaml"))
    if registry_path is None:
        return ["error registry_path escapes workspace"]
    if registry_path.exists():
        try:
            registry = read_json(registry_path)
            validate_registry(registry, root, (old or {}).get("root_id", "agent-collaboration-root"))
        except (OSError, ValueError) as exc:
            return [f"error {registry_path}: {exc}"]
    else:
        registry = {
            "schema_version": SCHEMA,
            "root_id": (old or {}).get("root_id", "agent-collaboration-root"),
            "routes": [],
        }
    manifest_paths = [
        (old or {}).get("registry_path", DEFAULT_REGISTRY_PATH),
        (old or {}).get("baseline_path", DEFAULT_BASELINE_PATH),
        (old or {}).get("source_state_path", DEFAULT_SOURCE_STATE_PATH),
    ]
    if old:
        manifest_paths.extend(old.get("managed_files", []))
        manifest_paths.extend(old.get("project_owned_files", []))
    try:
        _preflight_file_targets(root, [path for path in manifest_paths if isinstance(path, str)])
    except ValueError as exc:
        return [f"error {exc}"]
    hashes = (old or {}).get("managed_hashes", {})
    for target, asset in WORKSPACE_ASSETS.items():
        if target in PROJECT_OWNED:
            continue
        path = root / target
        if path.exists():
            scaffold_hash = hashlib.sha256(_asset(asset).encode()).hexdigest()
            if _digest(path) != hashes.get(target) and _digest(path) != scaffold_hash:
                actions.append(f"preserve-conflict {path}")
    if any(action.startswith("preserve-conflict ") for action in actions):
        return actions
    try:
        discovered = _discover(root)
    except (OSError, ValueError) as exc:
        return [f"error discovered route: {exc}"]
    merged = _merge_registry(registry, discovered)
    # Validate the complete merged registry before creating or changing any
    # workspace files.  Discovery can legitimately find a legacy Route whose
    # generated id collides with an explicitly registered id; that must fail
    # closed instead of leaving an invalid registry for post-validation to
    # report after the write has already happened.
    try:
        validate_registry(merged, root, (old or {}).get("root_id", "agent-collaboration-root"))
    except (OSError, ValueError) as exc:
        return [f"error merged registry: {exc}"]
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
    agents = root / "AGENTS.md"
    _write(agents, _replace_block(agents.read_text(encoding="utf-8") if agents.exists() else "", AGENTS_BEGIN, AGENTS_END, _asset("workspace/AGENTS_BLOCK.md")), dry_run, actions)
    claude = root / "CLAUDE.md"
    _write(claude, _replace_block(claude.read_text(encoding="utf-8") if claude.exists() else "", CLAUDE_BEGIN, CLAUDE_END, _asset("CLAUDE_BLOCK.md")), dry_run, actions)
    gitignore = root / ".gitignore"
    _write(gitignore, _replace_block(gitignore.read_text(encoding="utf-8") if gitignore.exists() else "", GITIGNORE_BEGIN, GITIGNORE_END, _asset("workspace/GITIGNORE_BLOCK.txt")), dry_run, actions)
    for target, asset in WORKSPACE_ASSETS.items():
        if target in PROJECT_OWNED and (root / target).exists():
            continue
        _write(root / target, _asset(asset), dry_run, actions)
    for rel in WORKSPACE_CREATE:
        path = root / rel
        if path.exists():
            continue
        content = 'schema_version: "2.0"\ndocuments: []\n' if rel.endswith("index.yaml") else (_asset("workspace/.agents/config.yaml") if rel.endswith("config.yaml") else (_asset("workspace/.agents/settings.yaml") if rel.endswith("settings.yaml") else ""))
        _write(path, content, dry_run, actions)
    _write(registry_path, stable_json(merged), dry_run, actions)
    data = _workspace_manifest(root, old)
    data["managed_hashes"] = {rel: _digest(root / rel) for rel in WORKSPACE_ASSETS if rel not in PROJECT_OWNED and (root / rel).exists()}
    _write(manifest_path, stable_json(data), dry_run, actions)
    return actions


def validate_workspace(root: Path) -> Tuple[bool, List[str]]:
    root = root.expanduser().resolve()
    errors: List[str] = []
    manifest_path = root / ".agents" / "manifest.json"
    try:
        manifest = read_json(manifest_path)
        validate_manifest(manifest, root)
    except (OSError, ValueError) as exc:
        return False, [str(exc)]
    try:
        _preflight_file_targets(root)
    except ValueError as exc:
        return False, [str(exc)]
    agents = root / "AGENTS.md"
    if not agents.exists():
        errors.append("missing AGENTS.md")
    elif not agents.is_file():
        errors.append("AGENTS.md is not a file")
    else:
        text = agents.read_text(encoding="utf-8")
        if AGENTS_BEGIN not in text or AGENTS_END not in text:
            errors.append("AGENTS.md ACHP managed block missing/incomplete")
        if "always-on" not in text.lower() or "self-evolution" not in text:
            errors.append("AGENTS.md admission boundary missing/incomplete")
        expected = _extract_block(_asset("workspace/AGENTS_BLOCK.md"), AGENTS_BEGIN, AGENTS_END)
        actual = _extract_block(text, AGENTS_BEGIN, AGENTS_END)
        if actual is not None and actual != expected:
            errors.append("AGENTS.md ACHP managed block drift")
    claude = root / "CLAUDE.md"
    if not claude.exists():
        errors.append("missing CLAUDE.md")
    elif not claude.is_file():
        errors.append("CLAUDE.md is not a file")
    else:
        text = claude.read_text(encoding="utf-8")
        if CLAUDE_BEGIN not in text or CLAUDE_END not in text or "@AGENTS.md" not in text:
            errors.append("CLAUDE.md ACHP router missing/incomplete")
        expected = _extract_block(_asset("CLAUDE_BLOCK.md"), CLAUDE_BEGIN, CLAUDE_END)
        actual = _extract_block(text, CLAUDE_BEGIN, CLAUDE_END)
        if actual is not None and actual != expected:
            errors.append("CLAUDE.md ACHP router drift")
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        errors.append("missing .gitignore")
    elif not gitignore.is_file():
        errors.append(".gitignore is not a file")
    else:
        text = gitignore.read_text(encoding="utf-8")
        if GITIGNORE_BEGIN not in text or GITIGNORE_END not in text:
            errors.append(".gitignore ACHP runtime block missing")
        expected = _extract_block(_asset("workspace/GITIGNORE_BLOCK.txt"), GITIGNORE_BEGIN, GITIGNORE_END)
        actual = _extract_block(text, GITIGNORE_BEGIN, GITIGNORE_END)
        if actual is not None and actual != expected:
            errors.append(".gitignore ACHP managed block drift")
    for rel in list(WORKSPACE_ASSETS) + WORKSPACE_CREATE:
        if not (root / rel).exists():
            errors.append(f"missing {rel}")
    registry_path = _safe_path(root, manifest.get("registry_path"))
    if registry_path is None:
        return False, errors + ["registry_path escapes workspace"]
    try:
        registry = read_json(registry_path)
        validate_registry(registry, root, manifest.get("root_id", "agent-collaboration-root"))
    except (OSError, ValueError) as exc:
        return False, errors + [str(exc)]
    expected_root_id = manifest.get("root_id", "agent-collaboration-root")
    managed_files = manifest.get("managed_files", [])
    managed_hashes = manifest.get("managed_hashes", {})
    for rel in managed_files:
        path = _safe_path(root, rel)
        if path is None:
            errors.append(f"managed file path is unsafe: {rel}")
            continue
        if not path.exists():
            errors.append(f"managed file missing: {rel}")
            continue
        if not path.is_file():
            errors.append(f"managed file is not a file: {rel}")
            continue
        expected_hash = managed_hashes.get(rel)
        if expected_hash is None:
            errors.append(f"managed file hash missing: {rel}")
        elif _digest(path) != expected_hash:
            errors.append(f"managed file hash mismatch: {rel}")
    for entry in registry.get("routes", []):
        route = _canonical_route(root, entry["path"])
        route_meta = route / ".agents/route.yaml"
        if route_meta.exists():
            try:
                meta = read_json(route_meta)
                validate_route_metadata(meta, route, root, entry, expected_root_id)
            except (OSError, ValueError) as exc:
                errors.append(f"route metadata invalid for {entry['id']}: {exc}")
        elif entry["status"] in {"active", "paused", "completed", "archived"}:
            errors.append(f"active route scaffold incomplete: {entry['id']}")
        if entry["status"] in {"active", "paused", "completed", "archived"}:
            if not (route / "AGENTS.md").exists() or not (route / ".agents/knowledge").is_dir() or not route_meta.exists():
                errors.append(f"active route scaffold incomplete: {entry['id']}")
    return not errors, errors


def route_operation(args: Any, asset_root: Path) -> int:
    workspace = args.workspace.expanduser().resolve()
    try:
        manifest = read_json(workspace / ".agents/manifest.json")
        validate_manifest(manifest, workspace)
        registry_path = _safe_path(workspace, manifest.get("registry_path"))
        if registry_path is None:
            raise ValueError("registry_path escapes workspace")
        registry = read_json(registry_path)
        validate_registry(registry, workspace, manifest.get("root_id", "agent-collaboration-root"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    if args.action == "list":
        for entry in registry["routes"]:
            print(f"{entry['id']}\t{entry['status']}\t{entry['path']}")
        return 0
    entry = next((item for item in registry["routes"] if item["id"] == args.route_id), None) if args.route_id else None
    try:
        route = _canonical_route(workspace, args.path) if args.path else (_canonical_route(workspace, entry["path"]) if entry else None)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1
    path_entry = next((item for item in registry["routes"] if route and item["path"] == route.relative_to(workspace).as_posix()), None) if route else None
    if path_entry and entry and path_entry["id"] != entry["id"] and args.action != "adopt":
        print("[FAIL] route id/path mismatch")
        return 1
    entry = path_entry or entry
    if args.action in {"create", "adopt"}:
        if route is None or (args.action == "adopt" and not route.is_dir()) or (route.exists() and not route.is_dir()):
            print("[FAIL] route target is invalid or missing")
            return 1
        rid = args.route_id or (entry["id"] if entry else route_id(route, args.display_name))
        if any(item["id"] == rid and item is not entry for item in registry["routes"]):
            print("[FAIL] route id already belongs to another route")
            return 1
        display = args.display_name or (entry["display_name"] if entry else route.name)
        if entry is None:
            route_rel = route.relative_to(workspace).as_posix()
            entry = {
                "id": rid,
                "display_name": display,
                "path": route_rel,
                "work_scope": "unknown",
                "status": "active" if args.action == "create" else "legacy-unmigrated",
                "migration_status": "pending",
                "agents_path": route_rel + "/AGENTS.md",
                "knowledge_root": route_rel + "/.agents/knowledge",
                "knowledge_index": route_rel + "/.agents/knowledge/index.yaml",
                "knowledge_index_status": "present",
                "source_repository": {"status": "unknown"},
                "execution_endpoints": {"status": "unknown"},
                "migration_contract": "0.2-required",
                "evidence": {"path": "local-verified", "execution": "unknown"},
            }
            registry["routes"].append(entry)
        route_meta = route / ".agents/route.yaml"
        if route_meta.exists():
            try:
                meta = read_json(route_meta)
                validate_route_metadata(meta, route, workspace, entry, manifest.get("root_id", "agent-collaboration-root"))
            except (OSError, ValueError) as exc:
                print(f"[FAIL] {exc}")
                return 1
        try:
            _preflight_route_targets(workspace, route)
        except ValueError as exc:
            print(f"[FAIL] {exc}")
            return 1
        actions: List[str] = []
        if not route.exists() and not args.dry_run:
            route.mkdir(parents=True)
        root_contract = _route_pointer(route, workspace / ".agents/coordination/ROOT-BASELINE.md")
        if not (route / "AGENTS.md").exists():
            _write(route / "AGENTS.md", _asset("workspace/ROUTE_AGENTS.md").replace("{{ROUTE_ID}}", rid).replace("{{ROUTE_NAME}}", display).replace("{{ROOT_CONTRACT}}", root_contract), args.dry_run, actions)
        if not route_meta.exists():
            _write(route_meta, stable_json({"schema_version": SCHEMA, "kind": "development-route", "route_id": rid, "display_name": display, "root_id": manifest["root_id"], "path": entry["path"], "state": entry["status"], "root_contract": root_contract, "knowledge_scope": ".agents/knowledge/", "source_state_ref": ".agents/state/source-state.yaml", "source_repository": {"status": "unknown"}, "execution_endpoints": {"status": "unknown"}}), args.dry_run, actions)
        for rel in [".agents/settings.yaml", ".agents/state/source-state.yaml", ".agents/knowledge/index.yaml", ".agents/knowledge/guides/.gitkeep", ".agents/knowledge/decisions/.gitkeep", ".agents/knowledge/observations/.gitkeep", ".agents/knowledge/archive/.gitkeep"]:
            path = route / rel
            if path.exists():
                continue
            content = _asset("workspace/.agents/settings.yaml") if rel.endswith("settings.yaml") else (_asset("workspace/.agents/state/source-state.yaml") if rel.endswith("source-state.yaml") else ('schema_version: "2.0"\ndocuments: []\n' if rel.endswith("index.yaml") else ""))
            _write(path, content, args.dry_run, actions)
        _write(registry_path, stable_json(registry), args.dry_run, actions)
        for action in actions:
            print(("[DRY-RUN] " if args.dry_run else "[APPLIED] ") + action)
        return 0
    if entry is None:
        print("[FAIL] route id not found")
        return 1
    try:
        route = _canonical_route(workspace, entry["path"])
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1
    route_meta = route / ".agents/route.yaml"
    if not route.is_dir() or not route_meta.exists():
        print("[FAIL] route metadata or directory missing")
        return 1
    try:
        meta = read_json(route_meta)
        validate_route_metadata(meta, route, workspace, entry, manifest.get("root_id", "agent-collaboration-root"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    actions: List[str] = []
    if args.action == "validate":
        print("[OK] route metadata and preserved route surface are valid")
        return 0
    if args.action == "set-state":
        if args.state not in STATES:
            print("[FAIL] invalid route state")
            return 1
        entry["status"] = args.state
        meta["state"] = args.state
    elif args.action == "rename":
        entry["display_name"] = args.display_name or entry["display_name"]
        meta["display_name"] = entry["display_name"]
    else:
        print(f"[FAIL] unsupported route action: {args.action}")
        return 1
    _write(route_meta, stable_json(meta), args.dry_run, actions)
    _write(registry_path, stable_json(registry), args.dry_run, actions)
    for action in actions:
        print(("[DRY-RUN] " if args.dry_run else "[APPLIED] ") + action)
    return 0


def main(argv: List[str]) -> int:
    if not argv:
        return 2
    if argv[0] == "workspace":
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["bootstrap", "adopt", "upgrade", "repair", "validate", "uninstall"])
        parser.add_argument("--root", type=Path, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--purge-data", action="store_true")
        args = parser.parse_args(argv[1:])
        if args.action == "validate":
            ok, problems = validate_workspace(args.root)
            print("[OK] Project Collaboration Root validated." if ok else "[FAIL] " + "; ".join(problems))
            return 0 if ok else 1
        if args.action == "uninstall":
            print("[FAIL] workspace uninstall requires a reviewed ownership plan")
            return 1
        actions = workspace_install(args.root, args.action, args.dry_run)
        for action in actions:
            print(("[DRY-RUN] " if args.dry_run else "[APPLIED] ") + action)
        if any(action.startswith(("error ", "preserve-conflict ")) for action in actions):
            return 1
        if not args.dry_run:
            ok, problems = validate_workspace(args.root)
            if not ok:
                print("[FAIL] " + "; ".join(problems))
                return 1
        return 0
    if argv[0] == "route":
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["create", "adopt", "validate", "list", "set-state", "rename"])
        parser.add_argument("--workspace", type=Path, required=True)
        parser.add_argument("--path")
        parser.add_argument("--route-id")
        parser.add_argument("--display-name")
        parser.add_argument("--state")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv[1:])
        return route_operation(args, _skill_root() / "assets" / "scaffold")
    return 2
