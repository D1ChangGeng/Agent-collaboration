"""Bind receiving evidence into the existing Driver journal before Native I/O."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from runtime.codex_driver import DriverRejected
from runtime.receiver_contract import NativeHandoffContext, native_generation


def handoff_payload(driver, operation, payload, context):
    if context is None:
        return payload  # Preserve the exact canonical input of legacy callers.
    try:
        context = NativeHandoffContext.model_validate_json(
            context.model_dump_json() if isinstance(context, NativeHandoffContext) else json.dumps(context))
        session = getattr(driver, "thread_id", None) or getattr(driver, "session_id", None)
        if ((context.operation_id, context.command_id, context.message_id, context.driver_binding_id,
             context.native_session_ref, context.provider_generation, context.input_digest) !=
                (operation.operation_id, operation.command_id, operation.message_id, driver.binding_id,
                 session, native_generation(driver.binding_id, asdict(driver.identity), session),
                 hashlib.sha256(payload["text"].encode()).hexdigest())):
            raise ValueError("handoff context does not match the current Native operation")
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise DriverRejected("native handoff evidence is not bound to this operation") from error
    # DriverJournal.begin atomically commits this exact input with the existing
    # operation identity/fence before the function containing Native I/O runs.
    return {**payload, "handoff_context": context.model_dump(mode="json")}
