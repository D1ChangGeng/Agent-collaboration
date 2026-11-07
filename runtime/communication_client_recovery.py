"""Client actions over the existing authenticated recovery command and outbox."""
from __future__ import annotations

from runtime.communication_http import CommunicationHttpError
from runtime.receiver_recovery_operations import ReceiverRecoveryOperations


class ClientRecoveryService:
    def recover_receiver(self, project, receiver_ref, body, *, client_request_id):
        body = self._validate("RecoveryRequest", body)
        if not body["reason"].strip():
            raise CommunicationHttpError("invalid_argument", "An explicit recovery reason is required")
        if (not isinstance(receiver_ref, str) or not receiver_ref.strip() or len(receiver_ref) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in receiver_ref)):
            raise CommunicationHttpError("invalid_argument", "Invalid receiver reference")
        recovery = ReceiverRecoveryOperations(self.project_service)
        # submit commits the original issuer, command identity and outbox before
        # advance can contact a receiver. Exact retries observe that same work.
        operation = recovery.submit(project, receiver_ref, body, client_request_id, self.credential)
        try:
            advanced = recovery.advance(project, operation["operation_id"], self.credential)
            if advanced["operation_id"] != operation["operation_id"]:
                raise ValueError("recovery returned another operation")
            return self._validate("Operation", advanced)
        except Exception as error:
            # Never erase an accepted command or replay a possible effect.
            raise CommunicationHttpError(
                "observation_unavailable", "Recovery command committed; observe the original operation",
                status_code=503, retryable=False, operation_ref=operation["operation_id"],
                effect_state="committed" if body["action"] in {"inspect", "reconcile"} else "unknown",
            ) from error
