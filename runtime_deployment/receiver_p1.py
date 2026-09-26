"""P1 reference receiver deployment with an explicit no-model validation mode."""
from __future__ import annotations

import os

from runtime.domain import DomainAuthority
from runtime.receiver_entry import DeploymentCallbacks


def callbacks(config, deployment_policy_sha256):
    if os.environ.get("ACS_RECEIVER_P1_MODE") != "no-model-validation":
        raise RuntimeError("P1 receiver requires an explicitly configured native mode")
    dsn = os.environ.get("ACS_RECEIVER_DSN")
    if not dsn:
        raise RuntimeError("receiver Domain DSN is unavailable")
    authority = DomainAuthority(dsn)
    store = authority.receiver_transport
    endpoint_id = config.binding.registration.endpoint_id
    runtime_id = config.binding.registration.runtime_id

    def authorize_current(admission):
        return (admission.endpoint_id, admission.runtime_id) == (endpoint_id, runtime_id) \
            and store.current_authority(admission)

    def native_invoke(admission):
        if (admission.endpoint_id, admission.runtime_id) != (endpoint_id, runtime_id):
            raise RuntimeError("P1 receiver callback binding changed")
        return {
            "native_ack_ref": f"fixture-no-model:{admission.dispatch_id}",
            "model_invoked": False,
            "deployment_policy_sha256": deployment_policy_sha256,
        }

    return DeploymentCallbacks(
        deployment_policy_sha256=deployment_policy_sha256,
        endpoint_id=endpoint_id,
        runtime_id=runtime_id,
        authorize_current=authorize_current,
        native_invoke=native_invoke,
    )
