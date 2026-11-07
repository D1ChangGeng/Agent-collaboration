"""Valid-token scope refusal differs from expired/revoked authentication."""
import time
from types import SimpleNamespace

import pytest

from runtime.communication_client_native_links import ClientNativeLinkService
from runtime.communication_http import _problem
from runtime.errors import AuthorizationDenied
from runtime.models import AuthenticatedContext
from runtime.project_http import OAuthScopeDenied, TokenAuthorization


def token(scopes):
    context = AuthenticatedContext("tenant", "authority", "incarnation", "actor", "grant")
    access = SimpleNamespace(token="synthetic-bearer", expires_at=time.time() + 600, scopes=scopes,
        claims={"acs/checked_at": time.monotonic()})
    verifier = SimpleNamespace(settings=SimpleNamespace(authorization_refresh_seconds=30))
    return TokenAuthorization(access, context, verifier)


def test_current_credential_missing_scope_is_an_explicit_permission_refusal():
    authorization = token(["acs:connect", "runtime.read"])
    assert authorization.credential() == "synthetic-bearer"
    with pytest.raises(OAuthScopeDenied):
        authorization.authorize_permissions(("runtime.invoke",))


def test_tool_scope_uses_the_same_valid_token_denial_and_rest_403_classification():
    authorization = token(["acs:connect", "runtime.read"])
    catalog = {"tools": {"read_message": {"security_scopes": ["message.read"]}}}
    with pytest.raises(OAuthScopeDenied) as error:
        authorization.authorize_tool(catalog, "read_message")
    request = SimpleNamespace(state=SimpleNamespace(request_id="scope-test", effect_state="none", operation_ref=None))
    assert _problem(request, error.value).status_code == 403
    authorization.valid = False
    with pytest.raises(PermissionError) as lost:
        authorization.authorize_tool(catalog, "read_message")
    assert type(lost.value) is PermissionError and _problem(request, lost.value).status_code == 401


def test_native_link_maps_only_valid_credential_scope_refusal_to_domain_denial():
    authorization = token(["acs:connect", "runtime.read"])
    facade = ClientNativeLinkService()
    facade.project_service = SimpleNamespace(token_authorization=authorization, context=authorization.context)
    with pytest.raises(AuthorizationDenied):
        facade._native_link_transport_permissions(("runtime.invoke",))


@pytest.mark.parametrize("loss", ["revoked", "expired", "stale_observation"])
def test_authentication_loss_is_not_relabelled_as_a_valid_token_scope_denial(loss):
    authorization = token(["acs:connect", "runtime.read", "runtime.invoke"])
    if loss == "revoked":
        authorization.valid = False
    elif loss == "expired":
        authorization.access.expires_at = time.time() - 1
    else:
        authorization.checked_at -= 60
    facade = ClientNativeLinkService()
    facade.project_service = SimpleNamespace(token_authorization=authorization, context=authorization.context)
    with pytest.raises(PermissionError) as caught:
        facade._native_link_transport_permissions(("runtime.invoke",))
    assert type(caught.value) is PermissionError


def test_sufficient_token_scopes_continue_to_the_existing_core_permission_checks():
    authorization = token(["acs:connect", "runtime.read", "runtime.invoke"])
    facade = ClientNativeLinkService()
    facade.project_service = SimpleNamespace(token_authorization=authorization, context=authorization.context)
    assert facade._native_link_transport_permissions(("runtime.invoke",)) is None
