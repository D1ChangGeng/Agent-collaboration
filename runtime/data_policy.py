"""Domain-authorized Source and Artifact access adapters.

The filesystem implementations deliberately remain policy-agnostic.  This
module supplies the missing Runtime boundary: every byte operation is preceded
by a fresh PostgreSQL Grant check using the authenticated command identity.
The adapter never accepts tenant, scope, or permission values from payload
fields; those values are bound to the command and the immutable artifact ref.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from runtime.artifacts import LocalArtifactStore
from runtime.models import ArtifactRef, CommandEnvelope
from runtime.source_models import SourceRequest


class DomainBoundArtifactStore:
    """Apply a live Domain Grant check before each CAS operation."""

    def __init__(
        self,
        store: LocalArtifactStore,
        authority: Any,
        command: CommandEnvelope,
        *,
        read_permission: str = "artifact.read",
        write_permission: str = "artifact.write",
    ) -> None:
        self._store = store
        self._authority = authority
        self._command = command
        self._read_permission = read_permission
        self._write_permission = write_permission

    def put_bytes(self, data: bytes, *, kind: str = "other",
                  media_type: str = "application/octet-stream") -> ArtifactRef:
        self._authorize(self._write_permission)
        return self._store.put_bytes(data, kind=kind, media_type=media_type)

    @property
    def root(self) -> Path:
        return self._store.root

    @property
    def scope_id(self) -> str:
        return self._store.scope_id

    @property
    def max_bytes(self) -> int:
        return self._store.max_bytes

    def _authorize(self, permission: str, scope_id: str | None = None) -> None:
        with self._authority._connect() as connection, connection.cursor() as cursor:
            self._authority._authorize(
                self._command,
                cursor,
                permission,
                self.scope_id if scope_id is None else scope_id,
            )

    def authorized_source_callback(self) -> Callable[[SourceRequest], bool]:
        """Bind Source admission/readback to ``source.read``."""
        return source_authorizer(self._authority, self._command)

    def authorized_artifact_callback(
        self, *, permission: str | None = None,
    ) -> Callable[[object, str], bool]:
        """Bind Source CAS hooks to a live artifact Grant."""
        selected = permission or self._read_permission

        def authorize(value: object, operation: str) -> bool:
            scope_id = value.scope_id if isinstance(value, ArtifactRef) else None
            if scope_id is None and isinstance(value, dict):
                scope_id = value.get("scope_id")
            self._authorize(
                self._write_permission if operation == "write" else selected,
                scope_id,
            )
            return True

        return authorize

    def put_file(self, source: Path | str, *, kind: str = "other",
                 media_type: str = "application/octet-stream") -> ArtifactRef:
        self._authorize(self._write_permission)
        return self._store.put_file(source, kind=kind, media_type=media_type)

    def verify(self, ref: ArtifactRef) -> ArtifactRef:
        self._authorize(self._read_permission, ref.scope_id)
        return self._store.verify(ref)

    def read(self, ref: ArtifactRef) -> bytes:
        self._authorize(self._read_permission, ref.scope_id)
        return self._store.read(ref)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> Self:
        self._store.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._store.__exit__(*args)


def source_authorizer(
    authority: Any,
    command: CommandEnvelope,
    *,
    permission: str = "source.read",
) -> Callable[[SourceRequest], bool]:
    """Return a SourceService callback bound to a live Domain Grant."""

    def authorize(request: SourceRequest) -> bool:
        if request.tenant_id != command.tenant_id or request.scope_id == "":
            return False
        with authority._connect() as connection, connection.cursor() as cursor:
            authority._authorize(command, cursor, permission, request.scope_id)
        return True

    return authorize


def artifact_authorizer(
    authority: Any,
    command: CommandEnvelope,
    *,
    permission: str = "artifact.read",
) -> Callable[[object, str], bool]:
    """Return a callback for SourceService's actual CAS byte boundary."""

    def authorize(value: object, operation: str) -> bool:
        scope_id = value.scope_id if isinstance(value, ArtifactRef) else None
        if scope_id is None and isinstance(value, dict):
            scope_id = value.get("scope_id")
        selected = "artifact.write" if operation == "write" else permission
        with authority._connect() as connection, connection.cursor() as cursor:
            authority._authorize(command, cursor, selected, scope_id)
        return True

    return authorize
