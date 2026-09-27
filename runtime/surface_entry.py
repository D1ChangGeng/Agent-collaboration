"""Executable local transports. Configuration and credentials are operator-owned."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from importlib.metadata import version

from runtime.json_payload import MAX_COMMAND_BYTES
from runtime.surface_config import configured_service
from runtime.surfaces import SurfaceCommand, SurfaceReply, create_app, failure


class SafeArguments(argparse.ArgumentParser):
    def error(self, _message):
        # argparse otherwise repeats unknown arguments, potentially including a
        # credential accidentally supplied on argv. Never echo their values.
        raise ValueError("invalid process arguments")


def create_mcp_server(service, credential_provider):
    if version("mcp") != "2.2.0" or version("mcp-types") != "2.2.0":
        raise RuntimeError("unsupported MCP SDK profile")
    from mcp.server import MCPServer
    from mcp_types import CallToolResult, TextContent

    async def privacy_boundary(ctx, call_next):
        credential = credential_provider()
        if ctx.method == "tools/call":
            try:
                service.authenticate(credential)
            except PermissionError:
                safe = failure("UNAUTHENTICATED").model_dump(mode="json")
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(safe))],
                                      structured_content=safe, is_error=True)
        if credential and credential in json.dumps(ctx.params):
            from mcp.shared.exceptions import MCPError
            if ctx.method != "tools/call":
                raise MCPError(code=-32602, message="Invalid request")
            safe = failure("INPUT_INVALID").model_dump(mode="json")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(safe))],
                                  structured_content=safe, is_error=True)
        result = await call_next(ctx)
        # SDK 2.2's context middleware receives the already-sieved wire mapping
        # from call_next, not necessarily the handler's CallToolResult instance.
        if ctx.method == "tools/call" and isinstance(result, dict):
            if credential and credential in json.dumps(result):
                safe = failure("INPUT_INVALID").model_dump(mode="json")
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(safe))],
                                      structured_content=safe, is_error=True)
            structured = result.get("structuredContent")
            if isinstance(structured, dict) and structured.get("ok") is False:
                return result | {"isError": True}
            if result.get("isError") and structured is None:
                safe = failure("INPUT_INVALID").model_dump(mode="json")
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(safe))],
                                      structured_content=safe, is_error=True)
        if credential and isinstance(result, CallToolResult) and credential in result.model_dump_json():
            safe = failure("INPUT_INVALID").model_dump(mode="json")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(safe))],
                                  structured_content=safe, is_error=True)
        if (isinstance(result, CallToolResult) and isinstance(result.structured_content, dict)
                and result.structured_content.get("ok") is False):
            return result.model_copy(update={"is_error": True})
        return result

    server = MCPServer("agent-collaboration-runtime", version="1.0", log_level="CRITICAL",
                       middleware=[privacy_boundary])

    @server.tool(name="run", structured_output=True)
    def run(request: SurfaceCommand) -> SurfaceReply:
        """Submit a structured command using this process's authenticated role."""
        return service.handle(request, credential_provider())

    return server


def main(argv=None, *, delivery_endpoints=None):
    parser = SafeArguments(prog="acs-runtime", add_help=True)
    parser.add_argument("--config", default=os.environ.get("ACS_SURFACE_CONFIG"))
    parser.add_argument("transport", choices=("cli", "mcp", "http"))
    try:
        arguments = parser.parse_args(argv)
    except ValueError:
        print(failure("INPUT_INVALID").model_dump_json(), file=sys.stderr)
        return 2
    try:
        with configured_service(arguments.config, delivery_endpoints=delivery_endpoints) as (service, settings):
            if arguments.transport == "cli":
                raw = sys.stdin.buffer.read(MAX_COMMAND_BYTES + 1)
                try:
                    request = json.loads(raw) if len(raw) <= MAX_COMMAND_BYTES else None
                except (ValueError, UnicodeError):
                    request = None
                reply = service.handle(request, settings.credential())
                print(reply.model_dump_json())
                return 0 if reply.ok else 1
            if arguments.transport == "mcp":
                create_mcp_server(service, settings.credential).run(transport="stdio")
                return 0
            import uvicorn
            # Remote/TLS/Node identity transport is a separate deployment profile.
            # The config validator also rejects non-loopback addresses.
            uvicorn.run(create_app(service), host=settings.host, port=settings.port,
                        log_level="critical", access_log=False, log_config=None)
            return 0
    except Exception:  # noqa: BLE001 - no raw configuration, DSN or credential details may escape the process entrypoint
        logging.shutdown()
        print(failure("CONFIGURATION_INVALID").model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
