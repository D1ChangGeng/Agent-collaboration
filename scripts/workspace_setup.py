#!/usr/bin/env python3
"""Fail-closed Project Collaboration Workspace and Route operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_KIND = "project-collaboration-root"
SCHEMA = "0.3"
SUPPORTED_SCHEMAS = {"0.2", "0.3"}
STATES = {"discovered", "active", "paused", "completed", "archived"}
LEGACY_MIGRATION_STATE = "legacy-unmigrated"
DEPRECATED_REGISTRY_FIELDS = {
    "version",
    "agents_path",
    "knowledge_root",
    "knowledge_index",
    "work_scope",
    "migration_status",
    "migration_contract",
    "knowledge_index_status",
    "source_repository",
    "execution_endpoints",
    "evidence",
}
DEPRECATED_ROUTE_FIELDS = {
    "version",
    "display_name",
    "state",
    "knowledge_scope",
    "source_state_ref",
    "source_repository",
    "execution_endpoints",
    "evidence",
}
CANONICAL_REGISTRY_FIELDS = {"id", "path", "display_name", "status"}
CANONICAL_ROUTE_FIELDS = {"schema_version", "kind", "route_id", "root_id", "path", "root_contract"}
MANIFEST_CANONICAL_FIELDS = {
    "schema_version",
    "kind",
    "root_id",
    "management_root",
    "execution_repository_required",
    "setup_skill",
    "registry_path",
    "runtime_dependency_on_setup_skill",
}
MANIFEST_OPTIONAL_INTEGRITY_FIELDS = {
    "managed_files",
    "project_owned_files",
    "managed_hashes",
}
MANIFEST_DEPRECATED_FIELDS = {
    "version",
    "root_path",
    "created_at",
    "updated_at",
    "mode",
    "preserved_route_paths",
    "source_state_path",
    "source_state_contract_path",
    "baseline_path",
}
DEFAULT_REGISTRY_PATH = ".agents/coordination/routes.yaml"
DEFAULT_BASELINE_PATH = ".agents/coordination/ROOT-BASELINE.md"
DEFAULT_SOURCE_STATE_PATH = ".agents/protocol/SOURCE-STATE.md"
_REPARSE_POINT = 0x400

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
]
ROUTE_REQUIRED_FILES = [
    "AGENTS.md",
    ".agents/route.yaml",
    ".agents/settings.yaml",
    ".agents/knowledge/index.yaml",
]
ROUTE_REQUIRED_DIRS = [
    ".agents/knowledge/guides",
    ".agents/knowledge/decisions",
    ".agents/knowledge/observations",
    ".agents/knowledge/archive",
]
ROUTE_SCAFFOLD_FILES = [
    "AGENTS.md",
    ".agents/route.yaml",
    ".agents/settings.yaml",
    ".agents/knowledge/index.yaml",
    ".agents/knowledge/guides/.gitkeep",
    ".agents/knowledge/decisions/.gitkeep",
    ".agents/knowledge/observations/.gitkeep",
    ".agents/knowledge/archive/.gitkeep",
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


def _is_reparse(path: Path) -> bool:
    """Detect symlink/junction/reparse entries without following them."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        if os.name == "nt" and path.exists():
            attrs = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attrs & _REPARSE_POINT)
    except OSError as exc:
        raise ValueError(f"cannot inspect reparse state for {path}: {exc}") from exc
    return False


def _exact_root(path: Path, label: str) -> Path:
    """Return an absolute spelling while refusing redirected path components."""
    raw = Path(os.path.abspath(os.fspath(path.expanduser())))
    current = raw
    while True:
        if _is_reparse(current):
            raise ValueError(
                f"{label} must not use a symlink, junction, or reparse point: {path}"
            )
        if current == current.parent:
            return raw
        current = current.parent


def _path_has_reparse(root: Path, candidate: Path) -> bool:
    """Check existing components between root and candidate for redirection."""
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if _is_reparse(current):
            return True
    return False


def stable_json(value: Any) -> str:
    """Serialize control-plane data as strict, deterministic JSON text."""
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _parse_schema_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_SCHEMAS:
        raise ValueError(f"unsupported schema version in {field}: {value!r}")
    return value


def schema_version(data: Dict[str, Any], default: Optional[str] = None) -> str:
    """Read a schema version without accepting ambiguous or future values.

    ``version`` is retained as a read-only compatibility alias for old input,
    but it may not silently override a canonical ``schema_version``.  The
    previous prefix matching accepted values such as ``0.30`` and made a
    future schema look current; exact values keep the migration boundary
    fail-closed.
    """
    has_schema = "schema_version" in data
    has_legacy = "version" in data
    if has_schema:
        value = _parse_schema_value(data.get("schema_version"), "schema_version")
        if has_legacy:
            legacy = _parse_schema_value(data.get("version"), "version")
            if legacy != value:
                raise ValueError(
                    "schema_version conflicts with deprecated version field"
                )
        return value
    if has_legacy:
        return _parse_schema_value(data.get("version"), "version")
    if default is not None:
        return _parse_schema_value(default, "default")
    raise ValueError("schema_version is required")


def normalize_route_status(value: Any, allow_legacy: bool = True) -> str:
    """Map the v0.2 compatibility marker only while reading legacy input."""
    if value == LEGACY_MIGRATION_STATE and allow_legacy:
        return "discovered"
    return value


def _validated_schema(data: Dict[str, Any], context: str) -> str:
    version = schema_version(data)
    # A v0.3 writer must emit the canonical key.  The legacy ``version`` alias
    # remains readable only for v0.2 input; it must never be used to fill a
    # missing v0.3 field.
    if version == SCHEMA and "schema_version" not in data:
        raise ValueError(f"{context} must declare canonical schema_version")
    return version


def _canonical_registry_entry_with_options(
    entry: Dict[str, Any], allow_legacy: bool = True
) -> Dict[str, Any]:
    status = normalize_route_status(entry.get("status"), allow_legacy=allow_legacy)
    if not isinstance(status, str) or status not in STATES:
        raise ValueError(f"invalid route state for {entry.get('id')!r}")
    for field in ("id", "path", "display_name"):
        if not isinstance(entry.get(field), str) or not entry.get(field):
            raise ValueError(f"invalid route {field} for {entry.get('id')!r}")
    result = {
        "id": entry["id"],
        "display_name": entry["display_name"],
        "path": entry["path"],
        "status": status,
    }
    # Unknown extension keys are preserved during an explicit migration so a
    # setup upgrade cannot silently destroy project-owned metadata.  New
    # writers only create the four canonical fields above.
    for key, value in entry.items():
        if key not in CANONICAL_REGISTRY_FIELDS and key not in DEPRECATED_REGISTRY_FIELDS:
            if not isinstance(key, str):
                raise ValueError("route extension keys must be strings")
            _validate_json_value(value, f"route extension {key!r}")
            result[key] = value
    return result


def _canonical_registry(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the v0.3 registry shape without carrying deprecated fields."""
    version = schema_version(data)
    result = {
        "schema_version": SCHEMA,
        "root_id": data.get("root_id", "agent-collaboration-root"),
        "routes": [],
    }
    # Preserve explicitly namespaced/extension data during an explicit
    # migration.  Deprecated schema fields are intentionally not copied.
    for key, value in data.items():
        if key not in {"schema_version", "version", "root_id", "routes"}:
            if not isinstance(key, str):
                raise ValueError("registry extension keys must be strings")
            _validate_json_value(value, f"registry extension {key!r}")
            result[key] = value
    for entry in data.get("routes", []):
        result["routes"].append(
            _canonical_registry_entry_with_options(
                entry, allow_legacy=version == "0.2"
            )
        )
    result["routes"].sort(key=lambda item: item["id"])
    return result


def _validate_registry_extensions(data: Dict[str, Any]) -> None:
    """Validate extension values before any registry mutation is written."""
    for key, value in data.items():
        if key not in {"schema_version", "version", "root_id", "routes"}:
            _validate_json_value(value, f"registry extension {key!r}")
    routes = data.get("routes", [])
    if isinstance(routes, list):
        for index, entry in enumerate(routes):
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if key not in CANONICAL_REGISTRY_FIELDS and key not in DEPRECATED_REGISTRY_FIELDS:
                    if not isinstance(key, str):
                        raise ValueError("route extension keys must be strings")
                    _validate_json_value(value, f"route[{index}] extension {key!r}")


def _validate_optional_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"route {field} must be a non-empty string")


def _validate_deprecated_registry_fields(entry: Dict[str, Any], root: Path) -> None:
    def validate_pointer(value: Any, field: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid route {field}")
        if value in {"unknown", "unverified", "not-measured"}:
            return
        if _safe_path(root, value) is None:
            raise ValueError(f"route {field} escapes workspace")

    for field in ("agents_path", "knowledge_root", "knowledge_index", "work_scope"):
        if field in entry:
            validate_pointer(entry[field], field)
    for field in ("migration_status", "migration_contract", "knowledge_index_status"):
        if field in entry:
            _validate_optional_string(entry[field], field)

    for field in ("source_repository", "execution_endpoints"):
        if field not in entry:
            continue
        value = entry[field]
        if not isinstance(value, dict):
            raise ValueError(f"route {field} must be an object")
        if "status" in value:
            _validate_optional_string(value["status"], f"{field}.status")

    if "evidence" in entry:
        evidence = entry["evidence"]
        if not isinstance(evidence, dict):
            raise ValueError("route evidence must be an object")
        for field, value in evidence.items():
            if not isinstance(value, str):
                raise ValueError(f"route evidence.{field} must be a string")


def _validate_deprecated_route_fields(
    meta: Dict[str, Any],
    route: Path,
    workspace: Path,
    entry: Optional[Dict[str, Any]] = None,
    allow_legacy_status: Optional[bool] = None,
) -> None:
    """Read and validate v0.2 Route fields without making them authoritative."""
    if allow_legacy_status is None:
        allow_legacy_status = schema_version(meta) == "0.2"
    if "display_name" in meta:
        _validate_optional_string(meta["display_name"], "metadata display_name")
        if entry is not None and meta["display_name"] != entry.get("display_name"):
            raise ValueError("route metadata display_name does not match registry")

    if "state" in meta:
        state = normalize_route_status(meta["state"], allow_legacy=allow_legacy_status)
        if not isinstance(state, str) or state not in STATES:
            raise ValueError("route metadata state is invalid")
        if entry is not None and state != normalize_route_status(
            entry.get("status"), allow_legacy=allow_legacy_status
        ):
            raise ValueError("route metadata state does not match registry")

    if "knowledge_scope" in meta and meta["knowledge_scope"] != ".agents/knowledge/":
        raise ValueError("route metadata knowledge_scope is not the conventional path")
    if "source_state_ref" in meta and meta["source_state_ref"] != ".agents/state/source-state.yaml":
        raise ValueError("route metadata source_state_ref is not the conventional path")

    for field in ("source_repository", "execution_endpoints"):
        if field in meta:
            value = meta[field]
            if not isinstance(value, dict):
                raise ValueError(f"route metadata {field} must be an object")
            if "status" in value:
                _validate_optional_string(value["status"], f"metadata {field}.status")
    if "evidence" in meta:
        evidence = meta["evidence"]
        if not isinstance(evidence, dict):
            raise ValueError("route metadata evidence must be an object")
        for field, value in evidence.items():
            if not isinstance(value, str):
                raise ValueError(f"route metadata evidence.{field} must be a string")


def read_json(path: Path) -> Dict[str, Any]:
    def reject_nonstandard_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant is not allowed: {value}")

    try:
        text = path.read_text(encoding="utf-8")
        # Registry/manifest files deliberately use JSON, which is also valid
        # YAML 1.2.  Keeping the parser in the Python standard library avoids
        # an optional YAML dependency and gives deterministic fail-closed input
        # handling across supported hosts.
        value = json.loads(text, parse_constant=reject_nonstandard_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON-compatible YAML at {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected object at {path}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_digest_bytes(data: bytes) -> str:
    """Hash text content independent of the host's newline convention."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def _normalized_digest(path: Path) -> str:
    return _normalized_digest_bytes(path.read_bytes())


def _validate_json_value(
    value: Any, context: str, _seen: Optional[set[int]] = None
) -> None:
    """Reject extension values that cannot be persisted as strict JSON."""
    if _seen is None:
        _seen = set()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{context} contains a non-finite number")
        return
    if isinstance(value, list):
        marker = id(value)
        if marker in _seen:
            raise ValueError(f"{context} contains a cyclic value")
        _seen.add(marker)
        for index, item in enumerate(value):
            _validate_json_value(item, f"{context}[{index}]", _seen)
        _seen.remove(marker)
        return
    if isinstance(value, dict):
        marker = id(value)
        if marker in _seen:
            raise ValueError(f"{context} contains a cyclic value")
        _seen.add(marker)
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{context} contains a non-string object key")
            _validate_json_value(item, f"{context}.{key}", _seen)
        _seen.remove(marker)
        return
    raise ValueError(f"{context} is not JSON-compatible")


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
    raw_candidate = root / relative
    if _path_has_reparse(root, raw_candidate):
        return None
    candidate = raw_candidate.resolve()
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
    # Durable route paths use canonical POSIX spelling even on Windows.  Do
    # not silently accept aliases such as ``R/``, ``R//``, ``./R`` or
    # backslash-separated variants: aliases can make a registry appear valid
    # while producing a different spelling during the next upgrade.
    if "\\" in relative:
        raise ValueError(f"route path is not canonical: {relative}")
    raw = relative.replace("\\", "/")
    parts = raw.split("/")
    if ".." in parts:
        raise ValueError(f"route path escapes workspace: {relative}")
    if any(part in {"", "."} for part in parts):
        raise ValueError(f"route path is not canonical: {relative}")
    root = _exact_root(root, "workspace path")
    raw_candidate = root.joinpath(*parts)
    if _path_has_reparse(root, raw_candidate):
        raise ValueError(f"route path uses a symlink or reparse point: {relative}")
    candidate = raw_candidate.resolve()
    if not _contained(root, candidate):
        raise ValueError(f"route path escapes workspace: {relative}")
    if candidate == root:
        raise ValueError("route path points to workspace root")
    control = (root / ".agents").resolve()
    if candidate == control or control in candidate.parents:
        raise ValueError(f"route path uses workspace control directory: {relative}")
    canonical = candidate.relative_to(root).as_posix()
    if raw != canonical:
        raise ValueError(f"route path is not canonical: {relative}")
    return candidate


def _route_pointer(route: Path, target: Path) -> str:
    return Path(os.path.relpath(str(target), str(route))).as_posix()


def _validate_marker_pair(text: str, begin: str, end: str, label: str) -> None:
    """Require a managed block to be absent or exactly one well-ordered pair."""
    begin_count = text.count(begin)
    end_count = text.count(end)
    if (begin_count, end_count) == (0, 0):
        return
    if (begin_count, end_count) != (1, 1):
        raise ValueError(
            f"{label} managed block markers must occur as 0/0 or 1/1 "
            f"(found {begin_count}/{end_count})"
        )
    if text.index(begin) >= text.index(end):
        raise ValueError(f"{label} managed block begin marker must precede end marker")


def _validate_existing_managed_blocks(root: Path) -> None:
    """Validate all existing managed files before any setup write occurs."""
    for filename, begin, end in (
        ("AGENTS.md", AGENTS_BEGIN, AGENTS_END),
        ("CLAUDE.md", CLAUDE_BEGIN, CLAUDE_END),
        (".gitignore", GITIGNORE_BEGIN, GITIGNORE_END),
    ):
        path = root / filename
        if not path.exists():
            continue
        if _is_reparse(path):
            raise ValueError(f"managed target uses a symlink or reparse point: {path}")
        if not path.is_file():
            raise ValueError(f"managed target is not a file: {path}")
        _validate_marker_pair(path.read_text(encoding="utf-8"), begin, end, filename)


def validate_root_baseline(text: str, expected_schema: str = SCHEMA) -> None:
    """Validate a Root contract at the compatibility level required by its schema."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Root baseline is missing or empty")
    expected_schema = _parse_schema_value(expected_schema, "Root baseline schema")
    # A schema-0.2 Workspace may keep its project-owned legacy contract while
    # it is only being read, adopted, repaired, or validated.  The explicit
    # upgrade path calls this validator with the target schema (0.3) before any
    # machine-state write, so a legacy contract cannot silently survive a
    # manifest/registry migration.
    if expected_schema == "0.2":
        return

    lowered = " ".join(text.lower().split()).replace("`", "")
    if re.search(r"schema\s+0\.2\b", lowered):
        raise ValueError("Root baseline still declares Workspace schema 0.2")
    if not re.search(
        r"\bstatus\b\s*:\s*[^\r\n]*\bschema\s+(?:version\s+)?0\.3\b",
        text,
        flags=re.IGNORECASE,
    ):
        raise ValueError("Root baseline status must declare Workspace schema 0.3")

    # Keep this as a semantic check rather than a snapshot of the prose.  The
    # contract may say "stable identity" or "Route ID", and may qualify the
    # path as canonical, while still expressing the same four-field authority.
    # Require the four fields to occur in one registry-local window: otherwise
    # unrelated mentions scattered through a long project-owned document could
    # accidentally satisfy the contract while the registry shape is absent.
    registry_field_terms = (
        r"\b(?:route\s+id|route\s+identity|stable\s+(?:project\s+)?identity)\b",
        r"\b(?:canonical\s+)?path\b",
        r"\bdisplay\s+name\b",
        r"\blifecycle\s+(?:status|state)\b",
    )
    registry_field_window = False
    for match in re.finditer(r"\bregistry\b", lowered):
        window = lowered[max(0, match.start() - 180) : match.end() + 300]
        if all(re.search(term, window) for term in registry_field_terms):
            registry_field_window = True
            break

    # A field list alone is not enough: the startup contract must also make
    # Root-registry authority explicit for lifecycle/display, rather than
    # merely mentioning a registry as a path or file name.
    registry_authority_window = False
    for match in re.finditer(r"\broot\s+registry\b", lowered):
        window = lowered[max(0, match.start() - 120) : match.end() + 260]
        has_authority_word = bool(
            re.search(r"\b(?:single\s+)?authority\b|\bauthoritative\b|\bowns?\b|\bstores?\b|\bcontains?\b", window)
        )
        has_lifecycle = bool(re.search(r"\blifecycle\s+(?:status|state)\b", window))
        has_display = bool(re.search(r"\bdisplay\s+name\b", window))
        if has_authority_word and has_lifecycle and has_display:
            registry_authority_window = True
            break
    if not (registry_field_window and registry_authority_window):
        raise ValueError(
            "Root baseline must declare the canonical Route registry fields: "
            "identity, path, display name, and lifecycle status"
        )

    route_owned_source_state_path = bool(
        re.search(
            r"(?:optional|按需|when verified|only when verified).{0,180}"
            r"\.agents/state/source-state\.yaml",
            lowered,
        )
    )
    harness_or_source_state = bool(
        re.search(
            r"endpoint\s+facts?\s+belong\s+to\s+(?:the\s+)?current\s+harness\s+context"
            r".{0,120}route[-\s]+owned\s+source\s+state\s+evidence",
            lowered,
        )
    )
    source_evidence_authority = bool(
        re.search(
            r"(?:source\s+repository|execution\s+endpoint(?:\s+evidence)?)"
            r".{0,140}(?:belongs?\s+to|authority|maintained\s+in)"
            r".{0,140}route[-\s]+owned.{0,80}source\s+state\s+evidence",
            lowered,
        )
    )
    if not (
        route_owned_source_state_path
        or harness_or_source_state
        or source_evidence_authority
    ):
        raise ValueError(
            "Root baseline must assign Source Repository and Execution Endpoint "
            "evidence to an optional Route-owned .agents/state/source-state.yaml"
        )

    stale_pointer_patterns = (
        "source repository and execution endpoint fields are metadata pointers",
        "registry writes are limited to stable identity, path, lifecycle, and pointers",
    )
    for pattern in stale_pointer_patterns:
        if pattern in lowered:
            raise ValueError("Root baseline contains obsolete Root registry pointer wording")


def _replace_block(text: str, begin: str, end: str, block: str) -> str:
    _validate_marker_pair(text, begin, end, "managed file")
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
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    if text.index(begin) >= text.index(end):
        return None
    _, rest = text.split(begin, 1)
    body, _ = rest.split(end, 1)
    return body.strip()


def _legacy_managed_block_bodies(filename: str, current_body: str) -> set[str]:
    """Return the exact managed-block bodies accepted for schema 0.2 input.

    The v0.2 Workspace template predates the persistence simplification.  Its
    managed blocks remain valid compatibility input, but arbitrary edits are
    still drift and must not be silently accepted by validation.
    """
    bodies = {current_body}
    if filename == "AGENTS.md":
        old_body = current_body.replace(
            "- A Route Node owns its identity metadata, durable goals, decisions, knowledge,\n"
            "  and verified source evidence. The Root registry owns lifecycle status and\n"
            "  display name; live Session progress remains in the current Harness context.",
            "- A Route Node owns its goals, route-specific identity, state, knowledge, and\n"
            "  engineer-facing continuity.",
        ).replace(
            "- Harness/session context and capability observations are local to the running\n"
            "  environment. They are not required Project Collaboration Workspace state.",
            "- `.agents/runtime/` is machine/session-local and must not become project truth.",
        )
        if old_body != current_body:
            bodies.add(old_body)
    elif filename == ".gitignore":
        bodies.add(
            "# Machine/session-local observations are not shared project truth.\n"
            ".agents/runtime/*\n"
            "!.agents/runtime/.gitkeep"
        )
    return bodies


def _workspace_block_is_upgrade_owned(
    text: str, filename: str, input_schema: str
) -> bool:
    """Return whether an existing Workspace managed block may be refreshed.

    A schema-0.3 Workspace has no block ownership ledger.  A valid block that
    differs from the current scaffold is therefore project content and must be
    preserved until a human explicitly reviews it.  Schema-0.2 is a known
    compatibility input whose legacy block bodies are intentionally migrated by
    the explicit Workspace upgrade operation.
    """
    begin, end = {
        "AGENTS.md": (AGENTS_BEGIN, AGENTS_END),
        "CLAUDE.md": (CLAUDE_BEGIN, CLAUDE_END),
        ".gitignore": (GITIGNORE_BEGIN, GITIGNORE_END),
    }[filename]
    if begin not in text and end not in text:
        return True
    current = _extract_block(text, begin, end)
    if current is None:
        # Marker shape is checked before this helper; retain a defensive
        # refusal if a future caller bypasses that preflight.
        return False
    expected = _extract_block(
        _asset(
            {
                "AGENTS.md": "workspace/AGENTS_BLOCK.md",
                "CLAUDE.md": "CLAUDE_BLOCK.md",
                ".gitignore": "workspace/GITIGNORE_BLOCK.txt",
            }[filename]
        ),
        begin,
        end,
    )
    if current == expected:
        return True
    if input_schema == "0.2":
        return current in _legacy_managed_block_bodies(filename, expected or "")
    return False


def _write(path: Path, content: str, dry_run: bool, actions: List[str]) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(f"target is a directory, expected a file: {path}")
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    actions.append(f"write {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def _action_label(action: str, dry_run: bool) -> str:
    """Return a truthful CLI label for a planned/applied action.

    ``workspace_install`` deliberately returns terse, machine-inspectable
    action strings.  The CLI is responsible for presenting those facts to a
    person; in particular, an error or ownership conflict must never be shown
    as an applied write.
    """
    if action.startswith("error "):
        return "[FAIL]"
    if action.startswith("preserve-conflict "):
        return "[CONFLICT]"
    if action.startswith("refused "):
        return "[REFUSED]"
    if action.startswith("candidate "):
        return "[CANDIDATE]"
    if action.startswith("warning "):
        return "[WARNING]"
    return "[DRY-RUN]" if dry_run else "[APPLIED]"


def _print_actions(actions: List[str], dry_run: bool) -> None:
    for action in actions:
        print(f"{_action_label(action, dry_run)} {action}")


def _actions_failed(actions: List[str]) -> bool:
    return any(
        action.startswith(("error ", "preserve-conflict ", "refused "))
        for action in actions
    )


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "route"


def route_id(path: Path, display: Optional[str] = None) -> str:
    candidate = _slug(display or path.name)
    return candidate if candidate != "route" else "route-" + hashlib.sha1(str(path).encode()).hexdigest()[:8]


def validate_manifest(data: Dict[str, Any], root: Optional[Path] = None) -> None:
    version = _validated_schema(data, "workspace manifest")
    if "version" in data and version == SCHEMA:
        raise ValueError("workspace manifest deprecated version field is not allowed for schema 0.3")
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
    for key in ("registry_path",):
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"workspace manifest {key} must be a relative path")
        if root is not None and _safe_path(root, value) is None:
            raise ValueError(f"workspace manifest {key} escapes workspace")
    # The Root contract has one fixed baseline location.  Older manifests may
    # omit it because the location is derivable; if present, every spelling
    # must agree and non-default values fail closed.
    baseline = data.get("baseline_path", DEFAULT_BASELINE_PATH)
    if not isinstance(baseline, str) or not baseline:
        raise ValueError("workspace manifest baseline_path must be a relative path")
    if root is not None and _safe_path(root, baseline) is None:
        raise ValueError("workspace manifest baseline_path escapes workspace")
    if baseline != DEFAULT_BASELINE_PATH:
        raise ValueError(f"workspace manifest baseline_path must be {DEFAULT_BASELINE_PATH}")

    source_state_values = []
    for field in ("source_state_contract_path", "source_state_path"):
        if field in data:
            value = data[field]
            if not isinstance(value, str) or not value:
                raise ValueError(f"workspace manifest {field} must be a relative path")
            if root is not None and _safe_path(root, value) is None:
                raise ValueError(f"workspace manifest {field} escapes workspace")
            source_state_values.append((field, value))
    if source_state_values:
        if len({value for _, value in source_state_values}) != 1:
            raise ValueError("workspace manifest source-state pointers conflict")
        if source_state_values[0][1] != DEFAULT_SOURCE_STATE_PATH:
            raise ValueError(
                f"workspace manifest source-state pointer must be {DEFAULT_SOURCE_STATE_PATH}"
            )

    # Validate legacy metadata when it is present, but do not require it for a
    # v0.3 manifest.  These fields describe installation history or compatibility
    # aliases; they are never used as collaboration lifecycle or recovery state.
    for field in ("root_path", "created_at", "updated_at", "mode"):
        if field in data and (not isinstance(data[field], str) or not data[field]):
            raise ValueError(f"workspace manifest {field} must be a non-empty string")
    if "preserved_route_paths" in data:
        values = data["preserved_route_paths"]
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("workspace manifest preserved_route_paths must be a list of strings")
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
    reserved = (
        MANIFEST_CANONICAL_FIELDS
        | MANIFEST_OPTIONAL_INTEGRITY_FIELDS
        | MANIFEST_DEPRECATED_FIELDS
    )
    for key, value in data.items():
        if key not in reserved:
            if not isinstance(key, str):
                raise ValueError("workspace manifest extension keys must be strings")
            _validate_json_value(value, f"workspace manifest extension {key!r}")


def validate_registry(
    data: Dict[str, Any],
    root: Path,
    expected_root_id: str = "agent-collaboration-root",
    require_route_dirs: bool = True,
) -> None:
    version = _validated_schema(data, "routes registry")
    if version == SCHEMA and "version" in data:
        raise ValueError("routes registry deprecated version field is not allowed for schema 0.3")
    if data.get("root_id") != expected_root_id:
        raise ValueError("routes registry root_id is invalid")
    routes = data.get("routes")
    if not isinstance(routes, list):
        raise ValueError("routes registry must contain a list")
    _validate_registry_extensions(data)
    ids: set[str] = set()
    paths: set[str] = set()
    canonical: set[str] = set()

    for entry in routes:
        if not isinstance(entry, dict):
            raise ValueError("routes registry contains a non-object entry")
        if version == SCHEMA:
            deprecated = sorted(set(entry) & DEPRECATED_REGISTRY_FIELDS)
            if deprecated:
                raise ValueError(
                    "schema 0.3 route registry entry contains deprecated fields: "
                    + ", ".join(deprecated)
                )
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
        if require_route_dirs and not target.is_dir():
            raise ValueError(f"route directory missing: {rel}")
        if not isinstance(entry.get("display_name"), str) or not entry.get("display_name"):
            raise ValueError(f"invalid route display_name for {rid}")
        raw_status = entry.get("status")
        status = normalize_route_status(raw_status, allow_legacy=version == "0.2")
        if not isinstance(status, str) or status not in STATES:
            raise ValueError(f"invalid route state for {rid}")
        _validate_deprecated_registry_fields(entry, root)

        expected_agents = f"{rel}/AGENTS.md" if (target / "AGENTS.md").exists() else "unknown"
        expected_knowledge = f"{rel}/.agents/knowledge" if (target / ".agents/knowledge").exists() else "unknown"
        expected_index = f"{rel}/.agents/knowledge/index.yaml" if (target / ".agents/knowledge/index.yaml").exists() else "unknown"
        for field, expected in (
            ("agents_path", expected_agents),
            ("knowledge_root", expected_knowledge),
            ("knowledge_index", expected_index),
        ):
            if field in entry and entry[field] not in {"unknown", "unverified", "not-measured", expected}:
                raise ValueError(f"route {field} conflicts with canonical route path for {rid}")
        if "work_scope" in entry and entry["work_scope"] not in {"unknown", "unverified", "not-measured"}:
            expected_scope = next((f"{rel}/{name}" for name in ("Improve", "Implement") if (target / name).is_dir()), "unknown")
            if entry["work_scope"] != expected_scope:
                raise ValueError(f"route work_scope conflicts with canonical route path for {rid}")

        ids.add(rid)
        paths.add(rel)
        canonical.add(str(target))


def _discover(
    workspace: Path,
    expected_root_id: str = "agent-collaboration-root",
    include_paths: Optional[set[str]] = None,
    exclude_paths: Optional[set[str]] = None,
    strict_metadata: bool = True,
) -> List[Dict[str, Any]]:
    """Inspect top-level Route candidates without making them authoritative."""
    result: List[Dict[str, Any]] = []
    used: set[str] = set()
    exclude_paths = exclude_paths or set()
    if not workspace.exists():
        return result
    for child in sorted(workspace.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not ((child / "AGENTS.md").exists() or (child / ".agents").exists()):
            continue
        rel = child.relative_to(workspace).as_posix()
        if rel in exclude_paths:
            continue
        if include_paths is not None and rel not in include_paths:
            continue
        rid = route_id(child)
        if rid in used:
            rid += "-" + hashlib.sha1(rel.encode()).hexdigest()[:8]
        used.add(rid)
        route_meta = child / ".agents" / "route.yaml"
        existing_meta: Optional[Dict[str, Any]] = None
        meta_version: Optional[str] = None
        inspection_error: Optional[str] = None
        if route_meta.exists():
            try:
                existing_meta = read_json(route_meta)
                validate_route_metadata(
                    existing_meta,
                    child,
                    workspace,
                    expected_root_id=expected_root_id,
                )
                meta_version = schema_version(existing_meta)
                rid = existing_meta["route_id"]
            except (OSError, ValueError) as exc:
                if strict_metadata:
                    raise
                existing_meta = None
                inspection_error = str(exc)
        existing_status = normalize_route_status(
            existing_meta.get("state", "discovered"),
            allow_legacy=meta_version == "0.2",
        ) if existing_meta else "discovered"
        if existing_status not in STATES:
            existing_status = "discovered"
        candidate = {
            "id": rid,
            "display_name": existing_meta.get("display_name", child.name) if existing_meta else child.name,
            "path": rel,
            "status": existing_status,
        }
        if inspection_error is not None:
            candidate["inspection_error"] = inspection_error
        result.append(candidate)
    return result


def _merge_registry(
    existing: Dict[str, Any], discovered: List[Dict[str, Any]], canonicalize: bool = True
) -> Dict[str, Any]:
    if not canonicalize:
        # Adopt/repair may discover a Route that was not registered yet, but
        # they are not schema-migration operations. Preserve every existing
        # entry byte-for-byte at the data-model level and append only genuinely
        # new paths; replacing or normalizing legacy entries belongs to the
        # explicit upgrade path.
        result = dict(existing)
        existing_routes = list(existing.get("routes", []))
        known_paths = {
            entry.get("path")
            for entry in existing_routes
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        result["routes"] = existing_routes + [
            dict(item) for item in discovered if item.get("path") not in known_paths
        ]
        return result

    current = {entry["path"]: entry for entry in existing.get("routes", []) if isinstance(entry, dict) and isinstance(entry.get("path"), str)}
    existing_version = schema_version(existing)
    result = {
        "schema_version": SCHEMA,
        "root_id": existing.get("root_id", "agent-collaboration-root"),
        "routes": [],
    }
    for key, value in existing.items():
        if key not in {"schema_version", "version", "root_id", "routes"}:
            if not isinstance(key, str):
                raise ValueError("registry extension keys must be strings")
            _validate_json_value(value, f"registry extension {key!r}")
            result[key] = value
    for item in discovered:
        old = current.get(item["path"])
        if canonicalize:
            merged = dict(item)
            if old:
                for key, value in old.items():
                    if key not in CANONICAL_REGISTRY_FIELDS and key not in DEPRECATED_REGISTRY_FIELDS:
                        merged[key] = value
        if old:
            merged["id"] = old.get("id", item["id"])
            merged["display_name"] = old.get("display_name", item["display_name"])
            merged["status"] = normalize_route_status(
                old.get("status", item["status"]),
                allow_legacy=existing_version == "0.2",
            )
        if canonicalize:
            merged = _canonical_registry_entry_with_options(
                merged, allow_legacy=existing_version == "0.2"
            )
        result["routes"].append(merged)
    seen = {item["path"] for item in discovered}
    for old in existing.get("routes", []):
        if isinstance(old, dict) and old.get("path") not in seen:
            result["routes"].append(
                _canonical_registry_entry_with_options(
                    old, allow_legacy=existing_version == "0.2"
                )
            )
    result["routes"].sort(key=lambda item: str(item.get("id", item.get("path", ""))))
    return result


def _canonicalize_registry(data: Dict[str, Any]) -> Dict[str, Any]:
    """Build the v0.3 registry from already validated input."""
    return _canonical_registry(data)


def _validate_route_surfaces(
    registry: Dict[str, Any],
    root: Path,
    expected_root_id: str,
    skip_paths: Optional[set[str]] = None,
    require_scaffold: bool = True,
) -> None:
    """Validate registered Route metadata and, by default, the full scaffold."""
    skip_paths = skip_paths or set()
    for entry in registry.get("routes", []):
        if entry.get("path") in skip_paths:
            continue
        route = _canonical_route(root, entry["path"])
        if require_scaffold:
            _validate_route_scaffold(route)
        route_meta = route / ".agents/route.yaml"
        if route_meta.exists():
            validate_route_metadata(read_json(route_meta), route, root, entry, expected_root_id)


def _route_scaffold_problems(route: Path) -> List[str]:
    problems: List[str] = []
    if _is_reparse(route):
        return ["route directory uses a symlink or reparse point"]
    for rel in ROUTE_REQUIRED_FILES:
        path = route / rel
        if _path_has_reparse(route, path) or _is_reparse(path):
            problems.append(f"symlink or reparse point {rel}")
        elif not path.exists():
            problems.append(f"missing file {rel}")
        elif not path.is_file():
            problems.append(f"expected file {rel}")
    for rel in ROUTE_REQUIRED_DIRS:
        path = route / rel
        if _path_has_reparse(route, path) or _is_reparse(path):
            problems.append(f"symlink or reparse point {rel}")
        elif not path.exists():
            problems.append(f"missing directory {rel}")
        elif not path.is_dir():
            problems.append(f"expected directory {rel}")
    return problems


def _validate_route_scaffold(route: Path) -> None:
    problems = _route_scaffold_problems(route)
    if problems:
        raise ValueError("route scaffold incomplete: " + "; ".join(problems))


def _route_missing_scaffold(route: Path) -> List[str]:
    """Return only missing canonical Route scaffold entries."""
    problems = _route_scaffold_problems(route)
    unexpected = [
        item
        for item in problems
        if not item.startswith(("missing file ", "missing directory "))
    ]
    if unexpected:
        raise ValueError("route scaffold is not safely repairable: " + "; ".join(unexpected))
    missing: List[str] = []
    for rel in ROUTE_SCAFFOLD_FILES:
        path = route / rel
        if not path.exists():
            missing.append(rel)
    return missing


def _write_route_scaffold(
    route: Path,
    workspace: Path,
    rid: str,
    display: str,
    root_id: str,
    dry_run: bool,
    actions: List[str],
) -> None:
    """Create only missing Route setup surfaces; never replace existing files."""
    if not route.exists() and not dry_run:
        route.mkdir(parents=True)
    root_contract = _route_pointer(
        route, workspace / ".agents/coordination/ROOT-BASELINE.md"
    )
    agents = route / "AGENTS.md"
    if not agents.exists():
        _write(
            agents,
            _asset("workspace/ROUTE_AGENTS.md")
            .replace("{{ROUTE_ID}}", rid)
            .replace("{{ROUTE_NAME}}", display)
            .replace("{{ROOT_CONTRACT}}", root_contract),
            dry_run,
            actions,
        )
    route_meta = route / ".agents/route.yaml"
    if not route_meta.exists():
        _write(
            route_meta,
            stable_json(_route_metadata_payload(route, workspace, rid, root_id)),
            dry_run,
            actions,
        )
    for rel in ROUTE_SCAFFOLD_FILES:
        if rel in {"AGENTS.md", ".agents/route.yaml"}:
            continue
        path = route / rel
        if path.exists():
            continue
        if rel.endswith("settings.yaml"):
            content = _asset("workspace/.agents/settings.yaml")
        elif rel.endswith("index.yaml"):
            content = 'schema_version: "2.0"\ndocuments: []\n'
        else:
            content = ""
        _write(path, content, dry_run, actions)


def _validate_projected_route(
    route: Path,
    workspace: Path,
    entry: Dict[str, Any],
    rid: str,
    root_id: str,
) -> None:
    """Validate the Route identity and the scaffold that a plan will create.

    Dry-run must be useful for an existing partial Route even though the
    planned files are intentionally not written.  Validate every existing
    component, reject unsafe/non-missing conflicts, and validate a synthetic
    metadata document for a missing ``route.yaml``.
    """
    _route_missing_scaffold(route)
    route_meta = route / ".agents/route.yaml"
    if route_meta.exists():
        validate_route_metadata(
            read_json(route_meta),
            route,
            workspace,
            entry,
            root_id,
        )
    else:
        validate_route_metadata(
            _route_metadata_payload(route, workspace, rid, root_id),
            route,
            workspace,
            entry,
            root_id,
        )


def _workspace_manifest(
    root: Path, old: Optional[Dict[str, Any]], canonicalize: bool = True
) -> Dict[str, Any]:
    if old and not canonicalize:
        return dict(old)
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
    result = {
        "schema_version": SCHEMA,
        "kind": WORKSPACE_KIND,
        "root_id": old.get("root_id", "agent-collaboration-root"),
        "management_root": True,
        "execution_repository_required": False,
        "setup_skill": "agent-collaboration-setup",
        "runtime_dependency_on_setup_skill": False,
        "registry_path": registry_path,
        # Ownership and hashes are installer integrity metadata, not runtime
        # collaboration state. They remain optional compatibility metadata.
        # These fields are optional installer integrity metadata.  Existing
        # values are retained for compatibility; a fresh v0.3 manifest does
        # not need to carry them as collaboration state.
        **({"managed_files": managed_files} if "managed_files" in old else {}),
        **({"project_owned_files": project_owned_files} if "project_owned_files" in old else {}),
        **({"managed_hashes": old["managed_hashes"]} if "managed_hashes" in old else {}),
    }
    reserved = (
        MANIFEST_CANONICAL_FIELDS
        | MANIFEST_OPTIONAL_INTEGRITY_FIELDS
        | MANIFEST_DEPRECATED_FIELDS
    )
    for key, value in old.items():
        if key not in reserved:
            _validate_json_value(value, f"workspace manifest extension {key!r}")
            result[key] = value
    return result


def _refresh_managed_hashes(
    root: Path,
    manifest: Dict[str, Any],
    previous_hashes: Optional[Dict[str, str]] = None,
    refresh_paths: Optional[set[str]] = None,
) -> Dict[str, str]:
    """Refresh installer-owned hashes and preserve custom drift evidence."""
    managed_files = manifest.get("managed_files", [])
    if not isinstance(managed_files, list):
        managed_files = []
    previous_hashes = previous_hashes or {}
    refresh_paths = refresh_paths or set()
    refreshed: Dict[str, str] = {}
    for rel in managed_files:
        if not isinstance(rel, str):
            continue
        path = _safe_path(root, rel)
        if path is not None and path.is_file():
            if rel in refresh_paths:
                refreshed[rel] = _digest(path)
            elif rel in previous_hashes:
                refreshed[rel] = previous_hashes[rel]
            else:
                refreshed[rel] = _digest(path)
    return refreshed


def _preflight_file_targets(root: Path, extra_paths: Optional[List[str]] = None) -> None:
    """Reject file/directory collisions before any workspace write."""
    targets = ["AGENTS.md", "CLAUDE.md", ".gitignore"] + list(WORKSPACE_ASSETS) + list(WORKSPACE_CREATE) + [".agents/manifest.json"]
    targets.extend(extra_paths or [])
    root = _exact_root(root, "workspace path")
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
    workspace = _exact_root(workspace, "workspace path")
    route = route if route.is_absolute() else workspace / route
    if _is_reparse(route):
        raise ValueError(f"route target uses a symlink or reparse point: {route}")
    route = Path(os.path.abspath(os.fspath(route)))
    if route.exists() and not route.is_dir():
        raise ValueError(f"route target is not a directory: {route}")
    if route.exists() and not _contained(workspace, route.resolve()):
        raise ValueError(f"route target resolves outside workspace: {route}")
    parent = route
    while parent != workspace and _contained(workspace, parent):
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"route parent is a file, expected a directory: {parent}")
        parent = parent.parent
    for rel in ROUTE_SCAFFOLD_FILES:
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
    """Validate minimal Route identity plus read-compatible v0.2 fields."""
    version = _validated_schema(meta, "route metadata")
    if version == SCHEMA:
        deprecated = sorted(set(meta) & DEPRECATED_ROUTE_FIELDS)
        if deprecated:
            raise ValueError(
                "schema 0.3 route metadata contains deprecated fields: "
                + ", ".join(deprecated)
            )
    if meta.get("kind") != "development-route":
        raise ValueError("route metadata kind invalid")
    if not isinstance(meta.get("route_id"), str) or not meta.get("route_id"):
        raise ValueError("route metadata route_id is invalid")
    if meta.get("root_id") != expected_root_id:
        raise ValueError("route metadata root_id is invalid")
    expected_path = route.relative_to(workspace).as_posix()
    if meta.get("path") != expected_path:
        raise ValueError("route metadata path does not match registry path")
    expected_contract = _route_pointer(route, workspace / ".agents/coordination/ROOT-BASELINE.md")
    if meta.get("root_contract") != expected_contract:
        raise ValueError("route metadata Root contract pointer is invalid")
    if entry is not None:
        if meta.get("route_id") != entry.get("id"):
            raise ValueError("route metadata route_id does not match registry")
    for key, value in meta.items():
        if key not in CANONICAL_ROUTE_FIELDS and key not in DEPRECATED_ROUTE_FIELDS:
            _validate_json_value(value, f"route metadata extension {key!r}")
    _validate_deprecated_route_fields(
        meta,
        route,
        workspace,
        entry,
        allow_legacy_status=version == "0.2",
    )


def _route_upgrade_payload(
    meta: Dict[str, Any], route: Path, workspace: Path, rid: str, root_id: str
) -> Dict[str, Any]:
    """Remove only recognized compatibility fields during explicit upgrade."""
    canonical = _route_metadata_payload(route, workspace, rid, root_id)
    for key, value in meta.items():
        if key not in CANONICAL_ROUTE_FIELDS and key not in DEPRECATED_ROUTE_FIELDS:
            canonical[key] = value
    return canonical


def _route_metadata_payload(route: Path, workspace: Path, rid: str, root_id: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "kind": "development-route",
        "route_id": rid,
        "root_id": root_id,
        "path": route.relative_to(workspace).as_posix(),
        "root_contract": _route_pointer(route, workspace / ".agents/coordination/ROOT-BASELINE.md"),
    }


def _requested_route_paths(root: Path, include_routes: Optional[List[str]]) -> set[str]:
    requested: set[str] = set()
    for value in include_routes or []:
        route = _canonical_route(root, value)
        rel = route.relative_to(root).as_posix()
        if "/" in rel:
            raise ValueError(
                f"included Route must be a top-level candidate: {value}"
            )
        requested.add(rel)
    return requested


def workspace_install(
    root: Path,
    mode: str,
    dry_run: bool,
    include_routes: Optional[List[str]] = None,
) -> List[str]:
    actions: List[str] = []
    try:
        root = _exact_root(root, "workspace path")
    except ValueError as exc:
        return [f"error {exc}"]
    if root.exists() and not root.is_dir():
        return [f"error workspace target is not a directory: {root}"]
    try:
        _validate_existing_managed_blocks(root)
    except (OSError, ValueError) as exc:
        return [f"error managed block markers: {exc}"]
    manifest_path = root / ".agents" / "manifest.json"
    if mode in {"upgrade", "repair"} and not manifest_path.exists():
        return [f"error workspace manifest missing; {mode} requires an existing Workspace"]
    if mode == "bootstrap" and root.exists() and any(root.iterdir()):
        return ["error bootstrap requires an empty Workspace path; use adopt for existing content"]
    old: Optional[Dict[str, Any]] = None
    if manifest_path.exists():
        try:
            old = read_json(manifest_path)
            validate_manifest(old, root)
        except (OSError, ValueError) as exc:
            return [f"error {manifest_path}: {exc}"]
    baseline_rel = (old or {}).get("baseline_path", DEFAULT_BASELINE_PATH)
    baseline_path = _safe_path(root, baseline_rel)
    if baseline_path is None:
        return ["error Root baseline path escapes workspace"]
    if baseline_path.exists():
        try:
            if not baseline_path.is_file():
                raise ValueError(f"Root baseline is not a file: {baseline_path}")
            input_schema = schema_version(old) if old is not None else SCHEMA
            baseline_schema = SCHEMA if mode == "upgrade" else input_schema
            validate_root_baseline(
                baseline_path.read_text(encoding="utf-8"), baseline_schema
            )
        except (OSError, ValueError) as exc:
            if old is not None and schema_version(old) == "0.2" and mode == "upgrade":
                return [f"error Root baseline upgrade review required: {exc}"]
            return [f"error Root baseline: {exc}"]
    elif old is not None:
        return [f"error Root baseline missing: {baseline_path}"]
    registry_path = _safe_path(root, (old or {}).get("registry_path", ".agents/coordination/routes.yaml"))
    if registry_path is None:
        return ["error registry_path escapes workspace"]
    if old and not registry_path.exists() and mode in {"adopt", "repair"}:
        return [
            "error routes registry is missing; use explicit workspace upgrade to reconstruct it"
        ]
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
    # A missing manifest is not enough evidence to reconstruct a legacy
    # Workspace.  In particular, do not let adopt infer a v0.3 manifest and
    # rewrite an existing schema-0.2 registry: that is an explicit migration
    # boundary, not ordinary setup repair.
    if (
        old is None
        and registry_path.exists()
        and schema_version(registry) == "0.2"
        and mode == "adopt"
    ):
        return [
            "error workspace manifest missing; existing schema 0.2 registry "
            "requires explicit workspace upgrade before reconstruction"
        ]
    manifest_paths = [
        (old or {}).get("registry_path", DEFAULT_REGISTRY_PATH),
        (old or {}).get("baseline_path", DEFAULT_BASELINE_PATH),
        (old or {}).get(
            "source_state_contract_path",
            (old or {}).get("source_state_path", DEFAULT_SOURCE_STATE_PATH),
        ),
    ]
    if old:
        manifest_paths.extend(old.get("managed_files", []))
        manifest_paths.extend(old.get("project_owned_files", []))
    try:
        _preflight_file_targets(root, [path for path in manifest_paths if isinstance(path, str)])
    except ValueError as exc:
        return [f"error {exc}"]
    input_schema = schema_version(old) if old is not None else schema_version(registry)
    hashes = (old or {}).get("managed_hashes", {})
    if not isinstance(hashes, dict):
        hashes = {}
    for target, asset in WORKSPACE_ASSETS.items():
        if target in PROJECT_OWNED:
            continue
        path = root / target
        if path.exists():
            scaffold_hash = _normalized_digest_bytes(_asset(asset).encode())
            raw_digest = _digest(path)
            normalized_digest = _normalized_digest(path)
            # A missing hash means ownership has not been recorded.  During
            # adopt/bootstrap we still protect a non-scaffold file; explicit
            # upgrade/repair may refresh setup-managed assets without treating
            # absent historical hashes as runtime truth.
            recorded_hash = hashes.get(target)
            if recorded_hash is not None:
                conflict = (
                    raw_digest != recorded_hash
                    and normalized_digest != scaffold_hash
                )
            else:
                conflict = (
                    normalized_digest != scaffold_hash
                    and mode in {"adopt", "bootstrap"}
                ) or (
                    normalized_digest != scaffold_hash
                    and mode == "upgrade"
                    and input_schema == SCHEMA
                )
            if conflict:
                actions.append(f"preserve-conflict {path}")
    # A fresh schema-0.3 Workspace intentionally omits an integrity ledger.
    # During explicit upgrade, an existing setup-managed file that is not the
    # current scaffold therefore has no ownership proof and must not be
    # replaced.  This is the same fail-closed rule used by repository setup.
    if mode == "upgrade":
        for filename, begin, end, _asset_name in (
            ("AGENTS.md", AGENTS_BEGIN, AGENTS_END, "workspace/AGENTS_BLOCK.md"),
            ("CLAUDE.md", CLAUDE_BEGIN, CLAUDE_END, "CLAUDE_BLOCK.md"),
            (".gitignore", GITIGNORE_BEGIN, GITIGNORE_END, "workspace/GITIGNORE_BLOCK.txt"),
        ):
            path = root / filename
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8")
                owned = _workspace_block_is_upgrade_owned(text, filename, input_schema)
            except (OSError, UnicodeError, ValueError):
                owned = False
            if not owned:
                actions.append(f"preserve-conflict {path}")
    if any(action.startswith("preserve-conflict ") for action in actions):
        return actions
    expected_root_id = (old or {}).get("root_id", "agent-collaboration-root")
    registered_paths = {
        entry.get("path")
        for entry in registry.get("routes", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    try:
        requested_paths = _requested_route_paths(root, include_routes)
        # Candidate discovery is advisory.  A Route-like directory becomes
        # authoritative only when explicitly selected with --include-route;
        # malformed or partial unselected candidates must not block Root setup.
        candidates = _discover(root, expected_root_id, strict_metadata=False)
    except (OSError, ValueError) as exc:
        return [f"error discovered route: {exc}"]
    candidate_by_path = {item["path"]: item for item in candidates}
    missing_requested = sorted(
        path
        for path in requested_paths
        if path not in registered_paths and path not in candidate_by_path
    )
    if missing_requested:
        return [
            "error included Route is not a discovered top-level candidate: "
            + ", ".join(missing_requested)
        ]
    discovered = [
        candidate_by_path[path]
        for path in sorted(requested_paths - registered_paths)
    ]
    invalid_selected = sorted(
        f"{item['path']}: {item['inspection_error']}"
        for item in discovered
        if item.get("inspection_error")
    )
    if invalid_selected:
        return [
            "error included Route candidate is invalid: "
            + "; ".join(invalid_selected)
        ]

    # Legacy schema migration remains fail-closed when an unregistered
    # candidate already aliases a durable Route ID. The candidate is still not
    # registered; the explicit migration must resolve the ambiguity first.
    if mode == "upgrade" and schema_version(registry) == "0.2":
        ids = {
            entry.get("id"): entry.get("path")
            for entry in registry.get("routes", [])
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        for candidate in candidates:
            old_path = ids.get(candidate["id"])
            if old_path is not None and old_path != candidate["path"]:
                return [
                    "error merged registry: unregistered Route candidate ID "
                    f"collision: {candidate['id']} ({old_path}, {candidate['path']})"
                ]
    if mode in {"adopt", "repair"} and schema_version(registry) == "0.2":
        # Keep the v0.2 migration boundary fail-closed.  v0.2 registries
        # cannot safely accept a newly discovered v0.3 Route entry during an
        # ordinary adopt/repair, even though v0.3 Workspaces now leave
        # unregistered candidates untouched by default.
        legacy_unregistered = sorted(
            item["path"]
            for item in candidates
            if item.get("path") not in registered_paths
        )
        if legacy_unregistered:
            return [
                "error Workspace schema 0.2 cannot register newly discovered "
                "Routes during adopt/repair; run explicit workspace upgrade first: "
                + ", ".join(legacy_unregistered)
            ]
        new_paths = sorted(
            item["path"]
            for item in discovered
            if item.get("path") not in registered_paths
        )
        if new_paths:
            return [
                "error Workspace schema 0.2 cannot register newly discovered "
                "Routes during adopt/repair; run explicit workspace upgrade first: "
                + ", ".join(new_paths)
            ]
    # Existing metadata is only projected to the v0.3 shape by an explicit
    # Workspace upgrade.  New workspaces start canonical; adopt/repair keep
    # legacy bytes readable and avoid turning an ordinary setup run into a
    # migration.
    canonicalize_registry = old is None or mode == "upgrade"
    merged = _merge_registry(registry, discovered, canonicalize=canonicalize_registry)
    # Validate the complete merged registry before creating or changing any
    # workspace files.  Discovery can legitimately find a legacy Route whose
    # generated id collides with an explicitly registered id; that must fail
    # closed instead of leaving an invalid registry for post-validation to
    # report after the write has already happened.
    try:
        validate_registry(merged, root, expected_root_id)
        _validate_route_surfaces(merged, root, expected_root_id)
    except (OSError, ValueError) as exc:
        return [f"error merged registry: {exc}"]
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
    # Existing managed blocks are preserved during adopt/repair.  Replacing a
    # valid legacy block is an explicit upgrade concern; ordinary adoption or
    # repair may create a missing block, but must not silently rewrite one that
    # is already present.  Upgrade always installs the current block body.
    managed_targets = (
        ("AGENTS.md", AGENTS_BEGIN, AGENTS_END, "workspace/AGENTS_BLOCK.md"),
        ("CLAUDE.md", CLAUDE_BEGIN, CLAUDE_END, "CLAUDE_BLOCK.md"),
        (".gitignore", GITIGNORE_BEGIN, GITIGNORE_END, "workspace/GITIGNORE_BLOCK.txt"),
    )
    preserve_existing_blocks = mode in {"adopt", "repair"}
    for filename, begin, end, asset in managed_targets:
        path = root / filename
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if preserve_existing_blocks and path.exists() and _extract_block(existing, begin, end) is not None:
            continue
        _write(path, _replace_block(existing, begin, end, _asset(asset)), dry_run, actions)
    refreshed_assets: set[str] = set()
    for target, asset in WORKSPACE_ASSETS.items():
        if target in PROJECT_OWNED and (root / target).exists():
            continue
        path = root / target
        existed = path.exists()
        if existed and mode in {"adopt", "repair"}:
            continue
        _write(path, _asset(asset), dry_run, actions)
        if not existed:
            refreshed_assets.add(target)
    for rel in WORKSPACE_CREATE:
        path = root / rel
        if path.exists():
            continue
        content = 'schema_version: "2.0"\ndocuments: []\n' if rel.endswith("index.yaml") else (_asset("workspace/.agents/config.yaml") if rel.endswith("config.yaml") else (_asset("workspace/.agents/settings.yaml") if rel.endswith("settings.yaml") else ""))
        _write(path, content, dry_run, actions)
    registry_changed = canonicalize_registry or merged != registry
    if registry_changed:
        _write(registry_path, stable_json(merged), dry_run, actions)
    canonicalize_manifest = old is None or mode == "upgrade"
    data = _workspace_manifest(root, old, canonicalize=canonicalize_manifest)
    # Fresh v0.3 workspaces do not need an integrity ledger.  When a legacy
    # manifest already carried one, refresh it as installer metadata so the
    # old drift guard remains usable without making the ledger collaboration
    # state.
    if old and "managed_hashes" in old:
        data["managed_hashes"] = _refresh_managed_hashes(
            root,
            data,
            old.get("managed_hashes") if isinstance(old.get("managed_hashes"), dict) else {},
            refresh_paths=(set(WORKSPACE_ASSETS) - PROJECT_OWNED)
            if mode == "upgrade"
            else refreshed_assets,
        )
    if canonicalize_manifest or (old and "managed_hashes" in old and refreshed_assets):
        _write(manifest_path, stable_json(data), dry_run, actions)
    return actions


def validate_workspace(root: Path) -> Tuple[bool, List[str]]:
    try:
        root = _exact_root(root, "workspace path")
    except (OSError, ValueError) as exc:
        return False, [str(exc)]
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
    try:
        _validate_existing_managed_blocks(root)
    except (OSError, ValueError) as exc:
        errors.append(f"managed block markers invalid: {exc}")
    baseline_path = _safe_path(
        root, manifest.get("baseline_path", DEFAULT_BASELINE_PATH)
    )
    if baseline_path is None:
        errors.append("Root baseline path escapes workspace")
    elif not baseline_path.exists():
        errors.append(f"missing Root baseline: {baseline_path}")
    elif not baseline_path.is_file():
        errors.append(f"Root baseline is not a file: {baseline_path}")
    else:
        try:
            validate_root_baseline(
                baseline_path.read_text(encoding="utf-8"),
                schema_version(manifest),
            )
        except (OSError, ValueError) as exc:
            errors.append(f"Root baseline invalid: {exc}")
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
        allowed = (
            _legacy_managed_block_bodies("AGENTS.md", expected or "")
            if schema_version(manifest) == "0.2"
            else {expected}
        )
        if actual is not None and actual not in allowed:
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
        allowed = (
            _legacy_managed_block_bodies(".gitignore", expected or "")
            if schema_version(manifest) == "0.2"
            else {expected}
        )
        if actual is not None and actual not in allowed:
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
    managed_hashes = manifest.get("managed_hashes")
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
        if managed_hashes:
            expected_hash = managed_hashes.get(rel)
            if expected_hash is None:
                errors.append(f"managed file hash missing: {rel}")
            elif _digest(path) != expected_hash:
                errors.append(f"managed file hash mismatch: {rel}")
    for entry in registry.get("routes", []):
        route = _canonical_route(root, entry["path"])
        try:
            _validate_route_scaffold(route)
        except (OSError, ValueError) as exc:
            errors.append(f"route scaffold invalid for {entry['id']}: {exc}")
            continue
        route_meta = route / ".agents/route.yaml"
        try:
            validate_route_metadata(
                read_json(route_meta), route, root, entry, expected_root_id
            )
        except (OSError, ValueError) as exc:
            errors.append(f"route metadata invalid for {entry['id']}: {exc}")
    return not errors, errors


def route_operation(args: Any, asset_root: Path) -> int:
    """Operate on one Route without sibling coupling or identity guessing."""
    try:
        workspace = _exact_root(args.workspace, "workspace path")
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    root_id = "agent-collaboration-root"
    try:
        manifest = read_json(workspace / ".agents/manifest.json")
        validate_manifest(manifest, workspace)
        root_id = manifest.get("root_id", root_id)
        registry_path = _safe_path(workspace, manifest.get("registry_path"))
        if registry_path is None:
            raise ValueError("registry_path escapes workspace")
        registry = read_json(registry_path)
        # Route operations are target-scoped.  The selected Route is validated
        # below, while a missing or incomplete sibling remains a Workspace-wide
        # validation concern rather than blocking unrelated work here.
        validate_registry(registry, workspace, root_id, require_route_dirs=False)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    if args.action == "list":
        for item in registry["routes"]:
            print(f"{item['id']}\t{item['status']}\t{item['path']}")
        return 0

    if args.route_id is not None and (
        not isinstance(args.route_id, str) or not args.route_id.strip()
    ):
        print("[FAIL] route id must be a non-empty string")
        return 1
    if args.display_name is not None and (
        not isinstance(args.display_name, str) or not args.display_name.strip()
    ):
        print("[FAIL] display name must be a non-empty string")
        return 1

    entry_by_id = None
    if args.route_id is not None:
        entry_by_id = next(
            (item for item in registry["routes"] if item.get("id") == args.route_id),
            None,
        )

    route: Optional[Path] = None
    path_entry: Optional[Dict[str, Any]] = None
    if args.path:
        try:
            route = _canonical_route(workspace, args.path)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] {exc}")
            return 1
        route_rel = route.relative_to(workspace).as_posix()
        path_entry = next(
            (item for item in registry["routes"] if item.get("path") == route_rel),
            None,
        )
    elif entry_by_id is not None:
        try:
            route = _canonical_route(workspace, entry_by_id["path"])
        except (OSError, ValueError) as exc:
            print(f"[FAIL] {exc}")
            return 1

    if path_entry is not None and entry_by_id is not None:
        if path_entry.get("id") != entry_by_id.get("id"):
            print("[FAIL] route id/path mismatch")
            return 1
    elif args.path and entry_by_id is not None:
        # An explicitly supplied Route ID already identifies another path.
        # Never let a create/adopt request silently reuse that identity for a
        # different path, which would otherwise create an orphaned directory
        # or mutate the wrong Route.
        print("[FAIL] route id/path mismatch")
        return 1

    entry: Optional[Dict[str, Any]] = path_entry or entry_by_id
    if route is None:
        print("[FAIL] route path is required")
        return 1

    route_meta = route / ".agents/route.yaml"
    meta: Optional[Dict[str, Any]] = None
    if route_meta.exists():
        try:
            meta = read_json(route_meta)
            # Validate the Route's own identity before using it to fill an
            # unregistered path.  This preserves custom IDs during adoption.
            validate_route_metadata(meta, route, workspace, None, root_id)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] {exc}")
            return 1

    metadata_id = meta.get("route_id") if meta else None
    if entry is not None and metadata_id is not None and metadata_id != entry.get("id"):
        print("[FAIL] route metadata route_id does not match registry")
        return 1

    if args.action not in {"create", "adopt"} and entry is None:
        print("[FAIL] route id not found")
        return 1

    rid = (
        args.route_id
        or (entry.get("id") if entry else None)
        or metadata_id
        or route_id(route, args.display_name)
    )
    if args.route_id is not None and args.route_id != rid:
        print("[FAIL] route id/path mismatch")
        return 1
    if any(item.get("id") == rid and item is not entry for item in registry["routes"]):
        print("[FAIL] route id already belongs to another route")
        return 1

    display = (
        args.display_name
        or (entry.get("display_name") if entry else None)
        or (meta.get("display_name") if meta else None)
        or route.name
    )

    if args.action in {"create", "adopt"}:
        exists = route.exists()
        if exists and not route.is_dir():
            print("[FAIL] route target is not a directory")
            return 1
        if args.action == "adopt" and not exists:
            print("[FAIL] route target is invalid or missing")
            return 1
        # Create establishes a new path.  Existing unregistered work belongs
        # to adopt; an already registered complete Route remains idempotent.
        if args.action == "create" and exists and path_entry is None:
            print("[FAIL] route path already exists; use route adopt")
            return 1

        route_rel = route.relative_to(workspace).as_posix()
        needs_registry_entry = entry is None
        if needs_registry_entry:
            entry = {
                "id": rid,
                "display_name": display,
                "path": route_rel,
                "status": "active" if args.action == "create" else "discovered",
            }
        else:
            rid = entry["id"]
            display = entry.get("display_name") or display

        try:
            missing = _route_missing_scaffold(route)
            _preflight_route_targets(workspace, route)
            _validate_projected_route(route, workspace, entry, rid, root_id)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] route plan rejected: {exc}")
            return 1
        needs_route_write = bool(missing)

        if schema_version(registry) == "0.2" and (
            needs_registry_entry or needs_route_write
        ):
            print(
                "[FAIL] Workspace schema 0.2 cannot accept v0.3 Route writes; "
                "run explicit workspace upgrade first"
            )
            return 1
        if args.action == "create" and path_entry is not None and needs_route_write:
            print("[FAIL] registered Route is incomplete; use route adopt")
            return 1

        if not needs_route_write and not needs_registry_entry:
            print("[OK] Route already exists and is unchanged")
            return 0

        if needs_registry_entry:
            registry["routes"].append(entry)
        actions: List[str] = []
        try:
            _write_route_scaffold(
                route,
                workspace,
                rid,
                display,
                root_id,
                args.dry_run,
                actions,
            )
            # Validate registry identity and path invariants without coupling
            # this target operation to the physical presence of sibling Routes.
            # The selected Route scaffold is validated independently below.
            validate_registry(
                registry,
                workspace,
                root_id,
                require_route_dirs=False,
            )
            if args.dry_run:
                validate_route_metadata(
                    _route_metadata_payload(route, workspace, rid, root_id),
                    route,
                    workspace,
                    entry,
                    root_id,
                )
            else:
                _validate_route_scaffold(route)
                validate_route_metadata(
                    read_json(route_meta), route, workspace, entry, root_id
                )
            if needs_registry_entry:
                _write(registry_path, stable_json(registry), args.dry_run, actions)
        except (OSError, TypeError, ValueError) as exc:
            print(f"[FAIL] route write rejected: {exc}")
            return 1
        _print_actions(actions, args.dry_run)
        return 0

    # Remaining operations validate only the selected Route.  A broken sibling
    # is reported by workspace-wide validation, not coupled into this action.
    if entry is None:
        print("[FAIL] route id not found")
        return 1
    if not route.is_dir() or not route_meta.exists():
        print("[FAIL] route metadata or directory missing")
        return 1
    try:
        _validate_route_scaffold(route)
        if meta is None:
            meta = read_json(route_meta)
        validate_route_metadata(meta, route, workspace, entry, root_id)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    actions: List[str] = []
    if args.action == "upgrade":
        try:
            canonical = _route_upgrade_payload(meta, route, workspace, entry["id"], root_id)
            upgraded_registry = _canonicalize_registry(registry)
            validate_registry(
                upgraded_registry,
                workspace,
                root_id,
                require_route_dirs=False,
            )
            upgraded_entry = next(
                item for item in upgraded_registry["routes"] if item["id"] == entry["id"]
            )
            validate_route_metadata(canonical, route, workspace, upgraded_entry, root_id)
            _write(route_meta, stable_json(canonical), args.dry_run, actions)
            _write(registry_path, stable_json(upgraded_registry), args.dry_run, actions)
        except (OSError, TypeError, ValueError, StopIteration) as exc:
            print(f"[FAIL] route upgrade rejected: {exc}")
            return 1
        _print_actions(actions, args.dry_run)
        return 0
    if args.action == "validate":
        print("[OK] route metadata and preserved route surface are valid")
        return 0
    if args.action == "set-state":
        if not isinstance(args.state, str) or args.state not in STATES:
            print("[FAIL] invalid route state")
            return 1
        if "state" in meta:
            print("[FAIL] Route metadata upgrade required before changing lifecycle state")
            return 1
        entry["status"] = args.state
    elif args.action == "rename":
        if "display_name" in meta:
            print("[FAIL] Route metadata upgrade required before renaming the Route")
            return 1
        if not isinstance(args.display_name, str) or not args.display_name.strip():
            print("[FAIL] display name must be a non-empty string")
            return 1
        entry["display_name"] = args.display_name
    else:
        print(f"[FAIL] unsupported route action: {args.action}")
        return 1
    try:
        validate_registry(
            registry,
            workspace,
            root_id,
            require_route_dirs=False,
        )
        _write(registry_path, stable_json(registry), args.dry_run, actions)
    except (OSError, TypeError, ValueError) as exc:
        print(f"[FAIL] registry write rejected: {exc}")
        return 1
    _print_actions(actions, args.dry_run)
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
        parser.add_argument(
            "--include-route",
            action="append",
            default=[],
            metavar="PATH",
            help="explicitly include a discovered top-level Route (repeatable)",
        )
        parser.add_argument(
            "--list-candidates",
            action="store_true",
            help="list discovered top-level Route candidates without writing",
        )
        args = parser.parse_args(argv[1:])
        if args.list_candidates:
            if args.action != "adopt":
                parser.error("--list-candidates is only valid with workspace adopt")
            try:
                candidates = _discover(
                    _exact_root(args.root, "workspace path"), strict_metadata=False
                )
            except (OSError, ValueError) as exc:
                print(f"[FAIL] candidate discovery rejected: {exc}")
                return 1
            for candidate in candidates:
                suffix = (
                    f"\t{candidate['inspection_error']}"
                    if candidate.get("inspection_error")
                    else ""
                )
                print(
                    f"{candidate['id']}\t{candidate['status']}\t"
                    f"{candidate['path']}{suffix}"
                )
            return 0
        if args.action == "validate":
            ok, problems = validate_workspace(args.root)
            print("[OK] Project Collaboration Root validated." if ok else "[FAIL] " + "; ".join(problems))
            return 0 if ok else 1
        if args.action == "uninstall":
            print("[FAIL] workspace uninstall requires a reviewed ownership plan")
            return 1
        actions = workspace_install(
            args.root,
            args.action,
            args.dry_run,
            include_routes=args.include_route,
        )
        _print_actions(actions, args.dry_run)
        if _actions_failed(actions):
            return 1
        if not args.dry_run:
            ok, problems = validate_workspace(args.root)
            if not ok:
                print("[FAIL] " + "; ".join(problems))
                return 1
        return 0
    if argv[0] == "route":
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["create", "adopt", "upgrade", "validate", "list", "set-state", "rename"])
        parser.add_argument("--workspace", type=Path, required=True)
        parser.add_argument("--path")
        parser.add_argument("--route-id")
        parser.add_argument("--display-name")
        parser.add_argument("--state")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv[1:])
        return route_operation(args, _skill_root() / "assets" / "scaffold")
    return 2
