"""Official MCP transports and current-session notification delivery."""
from __future__ import annotations

import json
import re
import uuid
from contextlib import asynccontextmanager
from importlib.metadata import version

import anyio
import psycopg
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated
from mcp.shared.exceptions import MCPError
from mcp_types import (
    CallToolResult,
    EmptyResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
)

INBOX = re.compile(r"acs://projects/([A-Za-z0-9][A-Za-z0-9._-]{0,127})/inbox\Z")


class _ProjectServer(Server):
    def get_capabilities(self, *args, **kwargs):
        result = super().get_capabilities(*args, **kwargs)
        # This server publishes explicit Inbox resource changes, not tool or
        # resource-catalog change streams. Do not advertise the SDK's generic
        # listen-handler defaults as capabilities this adapter implements.
        updates = {}
        if result.tools:
            updates["tools"] = result.tools.model_copy(update={"list_changed": False})
        if result.resources:
            updates["resources"] = result.resources.model_copy(update={"list_changed": False})
        return result.model_copy(update=updates)


class _TrackedBus(InMemorySubscriptionBus):
    def __init__(self):
        super().__init__()
        self.listener_count = 0

    def subscribe(self, listener):
        unsubscribe = super().subscribe(listener)
        self.listener_count += 1
        active = True

        def close():
            nonlocal active
            if active:
                active = False
                self.listener_count -= 1
                unsubscribe()
        return close


def _listener(dsn):
    connection = psycopg.connect(dsn, autocommit=True)
    try:
        connection.execute("LISTEN acs_domain_change")
        connection.execute("LISTEN acs_receipt_change")
    except BaseException:
        connection.close()
        raise
    return connection


def _wait_signal(connection):
    for _notification in connection.notifies(timeout=0.5, stop_after=1):
        break


def create_project_server(runtime=None, *, runtime_provider=None):
    if version("mcp") != "2.2.0" or version("mcp-types") != "2.2.0":
        raise RuntimeError("unsupported MCP transport SDK profile")
    def current_runtime():
        return runtime_provider() if runtime_provider else runtime

    @asynccontextmanager
    async def lifespan(_server):
        async with anyio.create_task_group() as tasks:
            yield {"tasks": tasks, "connections": {}}
            tasks.cancel_scope.cancel()

    async def publish_loop(state, *, task_status=anyio.TASK_STATUS_IGNORED):
        listener = None
        with anyio.CancelScope() as cancel:
            task_status.started(cancel)
            try:
                while True:
                    active_runtime = state["runtime"]
                    refresh = getattr(active_runtime, "refresh_authorization", None)
                    if refresh is not None:
                        try:
                            await refresh()
                        except Exception:  # noqa: BLE001 - authorization failure never publishes a wake
                            state["last_status"] = "authorization_pending"
                            await anyio.sleep(0.5)
                            continue
                    for uri, project_id in list(state["resources"].items()):
                        try:
                            keys = await anyio.to_thread.run_sync(active_runtime.service.pending_wake_keys,
                                project_id, state["session_ref"], state["connection_ref"], active_runtime.credential_provider())
                            newly_due = set(keys) - state["seen"].setdefault(uri, set())
                            if newly_due:
                                if state["modern"]:
                                    if not state["bus"].listener_count:
                                        continue
                                    await state["bus"].publish(ResourceUpdated(uri=uri))
                                else:
                                    await state["session"].send_resource_updated(uri)
                                state["seen"][uri].update(newly_due)
                            state["last_status"] = "observed"
                        except Exception:  # noqa: BLE001 - retain intent through outages; never emit private failures
                            state["last_status"] = "recovery_pending"
                    try:
                        if listener is None:
                            listener = await anyio.to_thread.run_sync(_listener, active_runtime.service.service.authority._dsn)
                        await anyio.to_thread.run_sync(_wait_signal, listener)
                    except (psycopg.Error, OSError):
                        if listener is not None:
                            await anyio.to_thread.run_sync(listener.close)
                            listener = None
                        await anyio.sleep(0.5)
            finally:
                if listener is not None:
                    with anyio.CancelScope(shield=True):
                        await anyio.to_thread.run_sync(listener.close)

    async def connection_state(ctx):
        # SDK 2.2 exposes a per-request session proxy around this connection.
        # The connection owns teardown and is stable across requests; a proxy
        # object's Python identity must not masquerade as Session continuity.
        connection = ctx.session._connection
        key = connection.state.setdefault("acs/connection_ref", "mcp-" + uuid.uuid4().hex)
        states = ctx.lifespan_context["connections"]
        active_runtime = current_runtime()
        context = active_runtime.service.context
        owner = (context.tenant_id, context.principal_ref, context.grant_ref, active_runtime.service.profile)
        if key in states and states[key]["owner"] != owner:
            raise MCPError(code=-32001, message="Session identity changed")
        if key not in states:
            state = {"connection_ref": key, "session_ref": key, "session": ctx.session,
                     "modern": ctx.protocol_version >= "2026-07-28", "resources": {}, "seen": {},
                     "bus": _TrackedBus(), "runtime": active_runtime, "owner": owner}
            state["listen"] = ListenHandler(state["bus"], max_subscriptions=8, max_buffered_events=128)
            state["cancel"] = await ctx.lifespan_context["tasks"].start(publish_loop, state)
            connection.exit_stack.callback(state["cancel"].cancel)
            connection.exit_stack.callback(state["listen"].close)
            connection.exit_stack.callback(states.pop, key, None)
            states[key] = state
        else:
            # A refreshed OAuth token may continue the same authenticated role.
            # The publisher must not retain the initialization token forever.
            states[key]["runtime"] = active_runtime
        return states[key]

    async def authorized_inbox(uri):
        active_runtime = current_runtime()
        match = INBOX.fullmatch(str(uri))
        if match is None:
            raise MCPError(code=-32602, message="Unknown project resource")
        project_id = match.group(1)
        try:
            await anyio.to_thread.run_sync(active_runtime.service.execute, "check_inbox",
                                          {"project_id": project_id}, active_runtime.credential_provider())
        except Exception:  # noqa: BLE001 - redact protected backend errors at the MCP boundary
            raise MCPError(code=-32001, message="Project resource unavailable") from None
        return project_id

    async def subscribe(ctx, params):
        uri = str(params.uri)
        project_id = await authorized_inbox(uri)
        state = await connection_state(ctx)
        active_runtime = state["runtime"]
        if len(state["resources"]) >= 32 and uri not in state["resources"]:
            raise MCPError(code=-32000, message="Subscription limit reached")
        try:
            await anyio.to_thread.run_sync(active_runtime.service.bind_notification_session, project_id,
                state["session_ref"], state["connection_ref"], active_runtime.credential_provider())
        except Exception:  # noqa: BLE001 - redact protected backend errors at the MCP boundary
            raise MCPError(code=-32001, message="Session subscription unavailable") from None
        state["resources"][uri] = project_id
        return EmptyResult()

    async def unsubscribe(ctx, params):
        state = await connection_state(ctx)
        state["resources"].pop(str(params.uri), None)
        return EmptyResult()

    async def listen(ctx, params):
        from mcp_types import SubscribeRequestParams
        notifications = params.notifications
        if (notifications.tools_list_changed or notifications.prompts_list_changed
                or notifications.resources_list_changed or not notifications.resource_subscriptions):
            raise MCPError(code=-32602, message="Subscribe to explicit project Inbox resources")
        state = await connection_state(ctx)
        for uri in notifications.resource_subscriptions:
            await subscribe(ctx, SubscribeRequestParams(uri=uri))
        return await state["listen"](ctx, params)

    async def list_tools(ctx, _params):
        try:
            state = await connection_state(ctx)
            result = await anyio.to_thread.run_sync(state["runtime"].tools_list)
            return ListToolsResult.model_validate(result)
        except Exception:  # noqa: BLE001 - redact protected backend errors at the MCP boundary
            raise MCPError(code=-32001, message="Tool discovery unavailable") from None

    async def call_tool(ctx, params):
        state = await connection_state(ctx)
        result = await anyio.to_thread.run_sync(state["runtime"].call, params.name, params.arguments or {})
        return CallToolResult.model_validate(result)

    async def list_resources(ctx, _params):
        try:
            active_runtime = (await connection_state(ctx))["runtime"]
            projects = await anyio.to_thread.run_sync(active_runtime.service.execute, "list_projects", {}, active_runtime.credential_provider())
            return ListResourcesResult.model_validate({"resources": [{
                "uri": f"acs://projects/{item['project_id']}/inbox", "name": item["project_id"] + " Inbox",
                "mimeType": "application/json", "description": "Durable responses and watched project changes"}
                for item in projects[1]["items"]]})
        except Exception:  # noqa: BLE001 - redact protected backend errors at the MCP boundary
            raise MCPError(code=-32001, message="Resource discovery unavailable") from None

    async def read_resource(ctx, params):
        active_runtime = (await connection_state(ctx))["runtime"]
        project_id = await authorized_inbox(params.uri)
        try:
            result = await anyio.to_thread.run_sync(active_runtime.service.execute, "check_inbox",
                                                   {"project_id": project_id}, active_runtime.credential_provider())
        except Exception:  # noqa: BLE001 - never return raw backend details across the MCP boundary
            raise MCPError(code=-32001, message="Project resource unavailable") from None
        return ReadResourceResult.model_validate({"contents": [{"uri": str(params.uri),
            "mimeType": "application/json", "text": json.dumps(result[1], default=str)}]})

    return _ProjectServer("agent-collaboration-runtime", version="0.1.0", lifespan=lifespan,
        instructions="Use list_projects and load_project for missing or stale project context. "
        "Every project-scoped action requires an explicit project_id. Retain response handles across reconnects. "
        "Subscribe to the project Inbox resource for completion wake signals; refetch it after reconnecting.",
        on_list_tools=list_tools, on_call_tool=call_tool, on_list_resources=list_resources,
        on_read_resource=read_resource, on_subscribe_resource=subscribe, on_unsubscribe_resource=unsubscribe,
        on_subscriptions_listen=listen)
