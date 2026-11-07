"""Bounded SSE transport with a fresh authorization check at every emit."""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import StreamingResponse

from runtime.communication_client_events import KINDS
from runtime.communication_http import PREFIX, CommunicationHttpError
from runtime.errors import AuthorizationDenied


@dataclass(frozen=True)
class EventStreamLimits:
    max_events: int = 256
    max_bytes: int = 1024 * 1024
    heartbeat_seconds: float = 15
    poll_seconds: float = 0.5
    slow_consumer_seconds: float = 15

    def __post_init__(self):
        if type(self.max_events) is not int or not 1 <= self.max_events <= 256:
            raise ValueError("invalid stream event buffer")
        if type(self.max_bytes) is not int or not 1024 <= self.max_bytes <= 1024 * 1024:
            raise ValueError("invalid stream byte buffer")
        for value, maximum in ((self.heartbeat_seconds, 60), (self.poll_seconds, 2), (self.slow_consumer_seconds, 60)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.01 <= value <= maximum:
                raise ValueError("invalid stream timing budget")


def _parameters(request):
    values, kinds = {}, []
    for key, value in request.query_params.multi_items():
        if key == "kinds":
            if value not in KINDS or value in kinds:
                raise CommunicationHttpError("invalid_argument", "Use distinct supported event kinds.")
            kinds.append(value)
        elif key == "after_cursor" and key not in values and 1 <= len(value) <= 2048:
            values[key] = value
        else:
            raise CommunicationHttpError("invalid_argument", "Unknown or duplicate event query parameter.")
    headers = request.headers.getlist("last-event-id")
    if len(headers) > 1 or headers and not 1 <= len(headers[0]) <= 2048:
        raise CommunicationHttpError("invalid_argument", "Use one valid Last-Event-ID.")
    after = values.get("after_cursor")
    if headers:
        if after is not None and after != headers[0]:
            raise CommunicationHttpError("invalid_argument", "after_cursor and Last-Event-ID must agree.")
        after = headers[0]
    if after is None:
        raise CommunicationHttpError("snapshot_required", "Start from a snapshot or saved event cursor.", status_code=409)
    return after, kinds or None


def _frame(event):
    data = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return ("id: " + event["cursor"] + "\nevent: " + event["kind"] + "\ndata: " + data + "\n\n").encode()


def _failure(error):
    permission = isinstance(error, (AuthorizationDenied, PermissionError)) or getattr(error, "code", None) in {
        "authorization_denied", "permission_changed", "cursor_invalid"}
    return ("permission.changed", "authorization_changed") if permission else ("resync.required", "event_observation_unavailable")


def register_event_routes(app, *, service, run, run_with_refresh, contract, limits=None):
    limits = limits or EventStreamLimits()

    @app.get(PREFIX + "/projects/{project_id}/events")
    async def events(project_id: str, request: Request):
        instance = await service(request)
        if not getattr(getattr(instance, "authority", None), "_communication_events_enabled", False):
            raise CommunicationHttpError("capability_unsupported", "Event streaming is not enabled.", status_code=409)
        after, kinds = _parameters(request)
        projects = request.state.project_service
        authorization = getattr(projects, "token_authorization", None)
        refresh = getattr(authorization, "refresh", None)
        if callable(refresh):
            await run(refresh)
        # Errors, including expired replay, still have ordinary HTTP status here.
        first = await run_with_refresh(authorization, instance.event_batch, project_id, after_cursor=after, kinds=kinds,
                                       limit=min(100, limits.max_events))

        async def generate():
            nonlocal first
            queue = asyncio.Queue(maxsize=limits.max_events)
            state = {"bytes": 0, "cursor": after, "auth": first.auth_revision, "closed": False, "ending": None}
            initial, first = first, None

            def clear():
                while not queue.empty():
                    queue.get_nowait()
                state["bytes"] = 0

            def end(kind, reason):
                if state["closed"]:
                    return
                state["closed"] = True
                state["ending"] = (kind, reason)
                clear()
                queue.put_nowait((None, (kind, reason)))

            async def produce():
                nonlocal initial
                batch, position = initial, after
                initial = None

                async def capacity(required_bytes=1):
                    started = asyncio.get_running_loop().time()
                    while queue.full() or state["bytes"] + required_bytes > limits.max_bytes:
                        if state["closed"] or await request.is_disconnected():
                            return False
                        if asyncio.get_running_loop().time() - started >= limits.slow_consumer_seconds:
                            end("resync.required", "slow_consumer")
                            return False
                        await asyncio.sleep(min(limits.poll_seconds, 0.1))
                        if callable(refresh):
                            await run(refresh)
                        await run(instance.event_current, project_id, expected_auth_revision=state["auth"])
                    return not state["closed"]

                try:
                    while not state["closed"]:
                        if await request.is_disconnected():
                            return
                        for event in batch.events:
                            encoded = _frame(contract("Event", event))
                            if len(encoded) > limits.max_bytes:
                                end("resync.required", "event_exceeds_buffer")
                                return
                            if not await capacity(len(encoded)):
                                return
                            state["bytes"] += len(encoded)
                            queue.put_nowait((encoded, event))
                        position = batch.after_cursor
                        if not batch.has_more:
                            await asyncio.sleep(limits.poll_seconds)
                        if not await capacity():
                            return
                        if callable(refresh):
                            await run(refresh)
                        batch = await run(instance.event_batch, project_id, after_cursor=position, kinds=kinds,
                            limit=min(100, max(1, limits.max_events - queue.qsize())))
                except (asyncio.CancelledError, GeneratorExit):
                    raise
                except Exception as error:  # noqa: BLE001 - close with minimal control metadata, never exception text.
                    end(*_failure(error))

            async def control(kind, reason):
                value = {"schema_version": "acs-event/1", "event_id": "control-" + uuid.uuid4().hex,
                    "cursor": state["cursor"], "project_id": project_id, "kind": kind, "resource_ref": None,
                    "resource_revision": 0, "committed_at": datetime.now(UTC).isoformat(),
                    "auth_revision": state["auth"], "payload": {"reason_code": reason, "reset_required": True}}
                return _frame(contract("Event", value))

            producer = asyncio.create_task(produce())
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        encoded, event = await asyncio.wait_for(queue.get(), timeout=limits.heartbeat_seconds)
                    except TimeoutError:
                        # A heartbeat has no resource, receipt, read or reply effect.
                        try:
                            if callable(refresh):
                                await run(refresh)
                            await run(instance.event_current, project_id, expected_auth_revision=state["auth"])
                        except Exception as error:  # noqa: BLE001 - clear private buffers on unavailable authority.
                            clear()
                            yield await control(*_failure(error))
                            return
                        yield b": heartbeat\n\n"
                        continue
                    if encoded is None:
                        yield await control(*event)
                        return
                    state["bytes"] -= len(encoded)
                    try:
                        if callable(refresh):
                            await run(refresh)
                        # The read transaction ends before the actual network yield.
                        await run(instance.event_current, project_id, expected_auth_revision=event["auth_revision"], event_id=event["event_id"])
                    except Exception as error:  # noqa: BLE001 - emit no stale metadata after any authority failure.
                        clear()
                        yield await control(*_failure(error))
                        return
                    if state["closed"] and state["ending"] is not None:
                        clear()
                        yield await control(*state["ending"])
                        return
                    state["cursor"], state["auth"] = event["cursor"], event["auth_revision"]
                    yield encoded
            finally:
                state["closed"] = True
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
                clear()

        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
