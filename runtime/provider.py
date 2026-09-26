from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommittedOperation:
    operation_id: str
    tenant_id: str
    command_id: str
    committed_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperationReference:
    operation_id: str
    workflow_id: str
    provider: str


class OperationReferenceStore(Protocol):
    def get(self, operation_id: str) -> OperationReference | None: ...

    def put(self, reference: OperationReference) -> None: ...


class InMemoryOperationReferenceStore:
    def __init__(self) -> None:
        self._items: dict[str, OperationReference] = {}

    def get(self, operation_id: str) -> OperationReference | None:
        return self._items.get(operation_id)

    def put(self, reference: OperationReference) -> None:
        self._items.setdefault(reference.operation_id, reference)

    def references(self) -> tuple[OperationReference, ...]:
        return tuple(self._items.values())


class TemporalReferenceProvider:
    def __init__(self, store: OperationReferenceStore) -> None:
        self._store = store

    def submit(self, operation: CommittedOperation) -> OperationReference:
        if operation.committed_at is None:
            raise ValueError("operation must be committed before provider submission")
        existing = self._store.get(operation.operation_id)
        if existing is not None:
            return existing
        reference = OperationReference(operation.operation_id, f"acs-p1/{operation.operation_id}", "temporal")
        self._store.put(reference)
        return reference
