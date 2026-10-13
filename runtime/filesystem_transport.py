"""Current machine file commands over existing pinned Node connections."""
from __future__ import annotations

import http.client
import json
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from runtime.machine_filesystem import FilesystemError, MachineFilesystem, TOOLS, WRITES
from runtime.receiver_crypto import sha256, sign, tls_fingerprint, verify
from runtime.remote_endpoint import RemoteNodeTransport

PATH = "/v1/filesystem"
FIELDS = frozenset({"schema_version", "request_id", "nonce", "tenant_id", "authority_id",
    "authority_incarnation", "principal_ref", "grant_ref", "endpoint_id", "endpoint_revision",
    "node_id", "machine_id", "boot_incarnation", "authority_key_id", "authority_key_revision",
    "operation", "arguments", "issued_at"})


class NodeFilesystemService:
    def __init__(self, config, signing_key, authorize, *, cwd=None):
        self.config, self.signing_key, self.authorize = config, signing_key, authorize
        self.backend = MachineFilesystem(config.binding.registration.machine_id, cwd=cwd,
                                         output_bytes=max(1024, config.maximum_body_bytes // 8))
        self._lock = threading.RLock()
        self._requests = {}
        with sqlite3.connect(config.ledger_path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS filesystem_requests ("
                "request_id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, "
                "state TEXT NOT NULL, result_json TEXT)")

    def handle(self, value):
        if self.config.access_mode != "owner":
            raise FilesystemError("profile_denied")
        command, signature = value["command"], value["signature"]
        if set(command) != FIELDS or command["schema_version"] != "acs-machine-files/1":
            raise FilesystemError("invalid_argument")
        registration = self.config.binding.registration
        expected = (registration.tenant_id, registration.authority_id, registration.authority_incarnation,
                    registration.endpoint_id, registration.endpoint_revision, registration.node_id,
                    registration.machine_id, registration.boot_incarnation, self.config.authority_key_id,
                    self.config.authority_key_revision)
        actual = tuple(command[key] for key in ("tenant_id", "authority_id", "authority_incarnation",
                    "endpoint_id", "endpoint_revision", "node_id", "machine_id", "boot_incarnation",
                    "authority_key_id", "authority_key_revision"))
        if actual != expected:
            raise FilesystemError("authentication_failed")
        verify(self.config.authority_public_key, signature, command)
        if self.authorize(command) is not True:
            raise FilesystemError("revoked")
        operation, arguments = command["operation"], command["arguments"]
        if operation not in TOOLS | {"filesystem_context"} or not isinstance(arguments, dict):
            raise FilesystemError("invalid_operation")
        request_hash = sha256(command)
        with self._lock:
            request_lock = self._requests.setdefault(command["request_id"], threading.RLock())
        with request_lock:
            with sqlite3.connect(self.config.ledger_path) as connection:
                previous = connection.execute("SELECT request_hash,state,result_json FROM filesystem_requests "
                    "WHERE request_id=?", (command["request_id"],)).fetchone()
                if previous:
                    if previous[0] != request_hash:
                        raise FilesystemError("request_conflict")
                    if previous[1] == "completed":
                        return json.loads(previous[2])
                    if operation in WRITES:
                        raise FilesystemError("write_uncertain", request_id=command["request_id"])
                else:
                    try:
                        connection.execute("INSERT INTO filesystem_requests VALUES (?,?,?,'started',NULL)",
                                           (command["request_id"], command["nonce"], request_hash))
                    except sqlite3.IntegrityError:
                        raise FilesystemError("request_conflict") from None
            try:
                if operation == "filesystem_context":
                    data = self.backend.context(arguments.get("cwd"), arguments.get("base_cwd"))
                else:
                    args = dict(arguments)
                    args["max_output_bytes"] = min(args.get("max_output_bytes", self.backend.output_bytes),
                                                   self.backend.output_bytes)
                    data = self.backend.execute(operation, args)
                result = {"ok": True, "data": data}
            except FilesystemError as error:
                result = {"ok": False, "error": {"code": error.code, **error.details}}
            except (ValueError, KeyError, TypeError):
                result = {"ok": False, "error": {"code": "invalid_argument"}}
            if self.authorize(command) is not True:
                raise FilesystemError("revoked")
            receipt = {"schema_version": "acs-machine-files-result/1", "request_id": command["request_id"],
                "nonce": command["nonce"], "request_hash": request_hash, "machine_id": registration.machine_id,
                "node_id": registration.node_id, "endpoint_revision": registration.endpoint_revision,
                "node_key_id": self.config.binding.node_key_id, "result": result,
                "observed_at": datetime.now(UTC).isoformat()}
            signed = {"receipt": receipt, "signature": sign(self.signing_key, receipt)}
            with sqlite3.connect(self.config.ledger_path) as connection:
                connection.execute("UPDATE filesystem_requests SET state='completed',result_json=? WHERE request_id=?",
                                   (json.dumps(signed), command["request_id"]))
            return signed


def node_request(adapter, context, operation, arguments, *, request=None):
    config = adapter.config
    registration = config.binding.registration
    if request is None:
        command = {"schema_version": "acs-machine-files/1", "request_id": uuid.uuid4().hex,
            "nonce": secrets.token_hex(32), "tenant_id": registration.tenant_id,
            "authority_id": registration.authority_id, "authority_incarnation": registration.authority_incarnation,
            "principal_ref": context.principal_ref, "grant_ref": context.grant_ref,
            "endpoint_id": registration.endpoint_id, "endpoint_revision": registration.endpoint_revision,
            "node_id": registration.node_id, "machine_id": registration.machine_id,
            "boot_incarnation": registration.boot_incarnation, "authority_key_id": config.authority_key_id,
            "authority_key_revision": config.authority_key_revision, "operation": operation,
            "arguments": arguments, "issued_at": datetime.now(UTC).isoformat()}
        request = {"command": command, "signature": sign(adapter._signing_key, command)}
    connection = http.client.HTTPSConnection(config.binding.locator_host, config.binding.locator_port,
        context=RemoteNodeTransport._context(), timeout=30)
    dispatched = False
    try:
        connection.connect()
        if tls_fingerprint(connection.sock.getpeercert(binary_form=True)) != registration.tls_certificate_sha256:
            raise FilesystemError("authentication_failed")
        encoded = json.dumps(request).encode()
        if len(encoded) > config.maximum_body_bytes:
            raise FilesystemError("request_too_large", max_bytes=config.maximum_body_bytes)
        # A failed request call may already have sent bytes. Preserve an
        # uncertain mutation for readback instead of issuing a fresh command.
        dispatched = True
        connection.request("POST", PATH, body=encoded, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(config.maximum_body_bytes + 1)
        if len(raw) > config.maximum_body_bytes:
            raise FilesystemError("filesystem_service_unavailable", status=response.status)
        if response.status != 200:
            try:
                code = json.loads(raw).get("code", "filesystem_service_unavailable")
            except (ValueError, TypeError):
                code = "filesystem_service_unavailable"
            raise FilesystemError(code, status=response.status)
        value = json.loads(raw)
        receipt = value["receipt"]
        verify(config.binding.node_public_key, value["signature"], receipt)
        command = request["command"]
        expected = (command["request_id"], command["nonce"], sha256(command), registration.machine_id,
                    registration.node_id, registration.endpoint_revision, config.binding.node_key_id)
        actual = tuple(receipt[key] for key in ("request_id", "nonce", "request_hash", "machine_id",
                                               "node_id", "endpoint_revision", "node_key_id"))
        if expected != actual:
            raise FilesystemError("authentication_failed")
        result = receipt["result"]
        if not result["ok"]:
            error = dict(result["error"])
            code = error.pop("code")
            raise FilesystemError(code, **error)
        return result["data"]
    except (OSError, TimeoutError, http.client.HTTPException):
        if dispatched and operation in WRITES:
            raise FilesystemError("write_uncertain", machine_id=registration.machine_id,
                                  request_id=request["command"]["request_id"]) from None
        raise FilesystemError("machine_offline", machine_id=registration.machine_id) from None
    finally:
        connection.close()
