from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """Trusted Source-admission input.

    Scope, Root and Route identities are supplied by the authenticated caller
    context. They are references, not grants. The Source service never accepts
    a body field that expands its configured authorized roots.
    """

    root: Path | str
    tenant_id: str
    scope_id: str
    root_id: str
    route_id: str
    expected_commit: str | None = None
    expected_tree: str | None = None
    allow_dirty: bool = False
    include_untracked: bool = True
    max_bytes: int | None = None
    secret_patterns: tuple[str, ...] = ()

    def normalized_root(self) -> Path:
        return Path(self.root)


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    mode: str
    size_bytes: int
    sha256: str
    artifact_ref: Mapping[str, Any]
    kind: str = "tracked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "artifact_ref": dict(self.artifact_ref),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Immutable source observation plus verified CAS references."""

    schema_version: str
    tenant_id: str
    scope_id: str
    root_id: str
    route_id: str
    repository_root: str
    source_commit: str
    source_tree: str
    git_version: str
    git_executable: str
    git_executable_sha256: str
    os_name: str
    python_version: str
    observed_at: str
    files: tuple[SourceFile, ...]
    diff_ref: Mapping[str, Any]
    untracked_manifest_ref: Mapping[str, Any]
    manifest_ref: Mapping[str, Any]
    excluded_paths: tuple[str, ...]
    dirty: bool
    working_tree_status_sha256: str
    source_class: str
    snapshot_sha256: str

    def manifest_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "scope_id": self.scope_id,
            "root_id": self.root_id,
            "route_id": self.route_id,
            "repository_root": self.repository_root,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "git_version": self.git_version,
            "git_executable": self.git_executable,
            "git_executable_sha256": self.git_executable_sha256,
            "os_name": self.os_name,
            "python_version": self.python_version,
            "observed_at": self.observed_at,
            "files": [item.to_dict() for item in self.files],
            "diff_ref": dict(self.diff_ref),
            "untracked_manifest_ref": dict(self.untracked_manifest_ref),
            "manifest_ref": dict(self.manifest_ref),
            "excluded_paths": list(self.excluded_paths),
            "dirty": self.dirty,
            "working_tree_status_sha256": self.working_tree_status_sha256,
            "source_class": self.source_class,
        }
        if include_digest:
            value["snapshot_sha256"] = self.snapshot_sha256
        return value
