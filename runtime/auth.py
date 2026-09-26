from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from runtime.models import AuthenticatedContext


class LocalCredentialUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocalCredentialAuthenticator:
    context: AuthenticatedContext

    @classmethod
    def from_environment(cls, context: AuthenticatedContext, variable: str = "ACS_P1_LOCAL_CREDENTIAL") -> LocalCredentialAuthenticator:
        secret = os.environ.get(variable)
        expected = context.credential_hash or os.environ.get("ACS_P1_LOCAL_CREDENTIAL_SHA256", "")
        if not secret or len(expected) != 64:
            raise LocalCredentialUnavailable(f"{variable} and ACS_P1_LOCAL_CREDENTIAL_SHA256 are required")
        return cls(context=AuthenticatedContext(context.tenant_id, context.authority_id, context.authority_incarnation, context.principal_ref, context.grant_ref, expected))

    def authenticate(self, secret: str | None) -> AuthenticatedContext:
        if not secret:
            raise LocalCredentialUnavailable("trusted local credential is required")
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, self.context.credential_hash):
            raise LocalCredentialUnavailable("trusted local credential rejected")
        return self.context
