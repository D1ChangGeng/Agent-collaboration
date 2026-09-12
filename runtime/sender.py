from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nacl.signing import SigningKey
from pydantic import BaseModel

from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import sha256, sign
from runtime.receiver_models import DeliveryAdmission, SignedRequest


@dataclass(frozen=True, slots=True)
class DeliveryIdentity:
    message_id: str
    command_id: str
    operation_id: str
    attempt_id: str
    dispatch_id: str
    accepted_revision: int
    accepted_state_digest: str
    envelope_digest: str
    selection_digest: str
    invocation_digest: str
    deadline: datetime


class AdmissionFactory:
    def __init__(self, config: ReceiverRuntimeConfig, signing_key: SigningKey,
                 identity: DeliveryIdentity):
        self.config, self.signing_key, self.identity = config, signing_key, identity

    @classmethod
    def from_key_reference(cls, config: ReceiverRuntimeConfig, key_path: str,
                           identity: DeliveryIdentity):
        from runtime.receiver_crypto import load_owner_signing_key
        return cls(config, load_owner_signing_key(key_path), identity)

    def request(self, purpose: str, body: BaseModel | dict[str, Any], *,
                boot_incarnation: str | None = None, journal_generation: int = 1,
                request_id: str | None = None, nonce: str | None = None) -> SignedRequest:
        body_value = body.model_dump(mode="json") if isinstance(body, BaseModel) else dict(body)
        registration = self.config.binding.registration
        identity = self.identity
        now = datetime.now(UTC)
        admission = DeliveryAdmission(
            purpose=purpose, authority_key_id=self.config.authority_key_id,
            authority_key_revision=self.config.authority_key_revision,
            tenant_id=registration.tenant_id, authority_id=registration.authority_id,
            authority_incarnation=registration.authority_incarnation,
            request_id=request_id or f"receiver-request-{uuid.uuid4()}",
            nonce=nonce or secrets.token_hex(32), path={
                "delivery.prepare": "/v1/delivery/prepare",
                "delivery.dispatch": "/v1/delivery/dispatch",
                "delivery.readback": "/v1/delivery/readback",
                "delivery.recover": "/v1/delivery/recover",
            }[purpose], body_sha256=sha256(body_value), message_id=identity.message_id,
            command_id=identity.command_id, operation_id=identity.operation_id,
            attempt_id=identity.attempt_id, dispatch_id=identity.dispatch_id,
            endpoint_id=registration.endpoint_id, endpoint_revision=registration.endpoint_revision,
            runtime_id=registration.runtime_id, runtime_revision=registration.runtime_revision,
            node_id=registration.node_id, machine_id=registration.machine_id,
            boot_incarnation=boot_incarnation or registration.boot_incarnation,
            scope_id=registration.scope_id, agent_slot_id=registration.agent_slot_id,
            accepted_revision=identity.accepted_revision,
            accepted_state_digest=identity.accepted_state_digest,
            envelope_digest=identity.envelope_digest, selection_digest=identity.selection_digest,
            invocation_digest=identity.invocation_digest, journal_generation=journal_generation,
            issued_at=now, deadline=self.identity.deadline,
        )
        return SignedRequest(admission=admission, body=body_value,
                             signature=sign(self.signing_key, admission))
