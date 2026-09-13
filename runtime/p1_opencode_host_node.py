"""A fixed OpenCode request surface over the existing restricted host Node."""

from __future__ import annotations

import os
import socket
import struct
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.native_delivery import NativeDeliveryAdapter
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.p1_codex_host_node import (
    CodexHostNodeEndpoint,
    CodexHostRequest,
    CodexHostResult,
    HostNodeRejected,
)
from runtime.receiver_paths import PathSecurityRejected, private_parent
from runtime.systemd_supervisor import SystemdUserSupervisor


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenCodeHostRequest(_Strict):
    schema_version: Literal["acs-p1-opencode-host-request/1"] = "acs-p1-opencode-host-request/1"
    action: Literal["dispatch", "readback"]
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{7,127}$")
    tenant_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    endpoint_id: str = Field(min_length=1, max_length=256)
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def internal(self) -> CodexHostRequest:
        return CodexHostRequest.model_validate(
            {**self.model_dump(), "schema_version": "acs-p1-codex-host-request/1"},
            strict=True,
        )


class OpenCodeHostResult(_Strict):
    schema_version: Literal["acs-p1-opencode-host-result/1"] = "acs-p1-opencode-host-result/1"
    run_id: str
    tenant_id: str
    message_id: str
    command_id: str
    operation_id: str
    status: str
    attempt_id: str | None = None
    dispatch_id: str | None = None
    pg_receipts: tuple[dict, ...] = ()
    node_receipts: tuple[dict, ...] = ()
    os_observation: dict | None = None
    scene_readback: dict | None = None
    scene_readback_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def from_internal(cls, value: CodexHostResult) -> OpenCodeHostResult:
        return cls.model_validate(
            {**value.model_dump(), "schema_version": "acs-p1-opencode-host-result/1"},
            strict=True,
        )


class OpenCodeHostNodeEndpoint(CodexHostNodeEndpoint):
    """Reuse Domain/Scope/Grant/boot fencing with an OpenCode Driver pin."""

    def _validate_native_adapter(self, adapter: NativeDeliveryAdapter) -> None:
        if (
            not isinstance(adapter, NativeDeliveryAdapter)
            or not isinstance(adapter.driver, OpenCodeNativeDriver)
            or not isinstance(adapter.driver.supervisor, SystemdUserSupervisor)
        ):
            raise HostNodeRejected("host endpoint requires OpenCode with host Systemd supervision")
        profile = adapter.driver.profile
        if (
            Path(profile.executable) != self.native_path
            or profile.config_path != self.config_path
            or profile.executable_sha256 != self.policy.native_sha256
            or profile.config_sha256 != self.policy.config_sha256
        ):
            raise HostNodeRejected("host OpenCode profile differs from pinned native artifacts")

    def handle(self, request):
        """Accept the public OpenCode request while reusing the shared core.

        ``OpenCodeHostUnixServer`` already converts its validated request before
        calling the endpoint, but the in-process scene service calls the
        endpoint directly.  Normalize that path here so the shared Domain /
        Node implementation never rejects a valid OpenCode schema merely
        because it expects the internal Codex-compatible representation.
        """
        if getattr(request, "schema_version", None) == "acs-p1-opencode-host-request/1":
            request = request.internal()
        return super().handle(request)


class OpenCodeHostUnixServer:
    """One authenticated, fixed-schema dispatch or readback per connection."""

    MAX_REQUEST = 8192
    MAX_RESPONSE = 262144

    def __init__(self, endpoint: OpenCodeHostNodeEndpoint, socket_path: Path) -> None:
        if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
            raise HostNodeRejected("Unix peer credentials are required")
        self.endpoint = endpoint
        self.socket_path = Path(socket_path)
        try:
            descriptor, _ = private_parent(self.socket_path.parent)
            os.close(descriptor)
        except PathSecurityRejected as error:
            raise HostNodeRejected("OpenCode host socket parent must be owner 0700") from error
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise HostNodeRejected("OpenCode host socket path already exists")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            self.socket.listen(8)
        except BaseException:
            self.socket.close()
            raise

    def serve_one(self, *, accept_timeout: float = 10.0) -> None:
        self.socket.settimeout(accept_timeout)
        peer, _ = self.socket.accept()
        with peer:
            try:
                _, uid, _ = struct.unpack(
                    "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                if uid != os.geteuid():
                    raise HostNodeRejected("OpenCode host peer UID differs")
                payload = bytearray()
                deadline = time.monotonic() + 10
                while len(payload) <= self.MAX_REQUEST:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise HostNodeRejected("OpenCode host request deadline expired")
                    peer.settimeout(remaining)
                    block = peer.recv(min(4096, self.MAX_REQUEST + 1 - len(payload)))
                    if not block:
                        break
                    payload.extend(block)
                    if b"\n" in block:
                        break
                if (
                    len(payload) > self.MAX_REQUEST
                    or payload.count(b"\n") != 1
                    or not payload.endswith(b"\n")
                ):
                    raise HostNodeRejected("OpenCode host request frame differs")
                try:
                    request = OpenCodeHostRequest.model_validate_json(payload[:-1], strict=True)
                except ValueError as error:
                    raise HostNodeRejected("OpenCode host request schema differs") from error
                observed = self.endpoint.handle(request.internal())
                result = (
                    observed if isinstance(observed, OpenCodeHostResult)
                    else OpenCodeHostResult.from_internal(observed)
                )
                data = result.model_dump_json().encode() + b"\n"
                if len(data) > self.MAX_RESPONSE:
                    data = b'{"schema_version":"acs-p1-opencode-host-error/1","state":"uncertain"}\n'
            except HostNodeRejected:
                data = b'{"schema_version":"acs-p1-opencode-host-error/1","state":"rejected"}\n'
            except Exception:  # noqa: BLE001 -- unknown dispatch outcome stays uncertain
                data = b'{"schema_version":"acs-p1-opencode-host-error/1","state":"uncertain"}\n'
            try:
                peer.settimeout(2)
                peer.sendall(data)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return

    def close(self) -> None:
        self.socket.close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
