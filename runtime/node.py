from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class JournalOperation:
    operation_id: str
    command_id: str
    message_id: str
    operation_kind: str
    payload_sha256: str


class OperationIdentityConflict(ValueError):
    pass


class NodeJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS journal(operation_id TEXT PRIMARY KEY, command_id TEXT NOT NULL, message_id TEXT NOT NULL, operation_kind TEXT NOT NULL, payload_sha256 TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def append(self, operation: JournalOperation) -> JournalOperation:
        with self._connect() as connection:
            row = connection.execute("SELECT command_id,message_id,operation_kind,payload_sha256 FROM journal WHERE operation_id=?", (operation.operation_id,)).fetchone()
            if row is not None:
                existing = JournalOperation(operation.operation_id, row[0], row[1], row[2], row[3])
                if existing != operation:
                    raise OperationIdentityConflict(operation.operation_id)
                return existing
            connection.execute("INSERT INTO journal(operation_id,command_id,message_id,operation_kind,payload_sha256) VALUES (?,?,?,?,?)", (operation.operation_id, operation.command_id, operation.message_id, operation.operation_kind, operation.payload_sha256))
        return operation

    def read(self, operation_id: str) -> JournalOperation | None:
        with self._connect() as connection:
            row = connection.execute("SELECT operation_id,command_id,message_id,operation_kind,payload_sha256 FROM journal WHERE operation_id=?", (operation_id,)).fetchone()
        return None if row is None else JournalOperation(*row)

    def digest(self, operation: JournalOperation) -> str:
        return hashlib.sha256(json.dumps(asdict(operation), sort_keys=True).encode()).hexdigest()
