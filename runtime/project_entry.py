"""Authenticated typed MCP entry point using the existing surface configuration."""
from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path

import anyio

from runtime.mcp_runtime import McpRuntime
from runtime.project_service import ProjectService
from runtime.project_source import ProjectSources
from runtime.surface_config import configured_service
from runtime.surface_entry import SafeArguments


async def serve_stdio(server):
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv=None, *, delivery_endpoints=None):
    parser = SafeArguments(prog="acs-project-runtime")
    parser.add_argument("--config", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--profile")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--http-config", type=Path)
    try:
        args = parser.parse_args(argv)
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        with configured_service(args.config, delivery_endpoints=delivery_endpoints) as (
            service, settings,
        ), ExitStack() as resources:
            sources = None
            configs = settings.artifact_configs()
            if configs and any(item.authorized_source_roots for item in configs):
                roots = (configs[0].authorized_source_roots if len(configs) == 1 else
                         {item.scope_id: item.authorized_source_roots for item in configs
                          if item.authorized_source_roots})
                sources = ProjectSources(service.authority._artifact_store, roots)
                resources.callback(sources.close)
            # Schema and project adoption are explicit operator steps. Starting
            # a client cannot provision identities, grants, or database tables.
            service.authenticate(settings.credential())
            if args.transport == "stdio":
                if args.http_config or not args.profile:
                    raise ValueError("stdio requires a Profile and no HTTP configuration")
                projects = ProjectService(service, catalog, profile=args.profile, sources=sources)
                runtime = McpRuntime(projects, settings.credential,
                                     presentation_timezone=settings.presentation_timezone)
                anyio.run(serve_stdio, runtime.create_server())
            else:
                import uvicorn

                from runtime.project_http import ProjectHttpSettings, create_http_app

                if args.http_config is None or args.profile:
                    raise ValueError("HTTP Profiles are selected only by explicit OAuth bindings")
                http_settings = ProjectHttpSettings.model_validate_json(args.http_config.read_bytes())
                app = create_http_app(service, catalog, http_settings, sources=sources,
                                      host=settings.host, port=settings.port)
                # Loopback-only backend. External ingress and OAuth consent are
                # operator actions, never implicit effects of starting Runtime.
                uvicorn.run(app, host=settings.host, port=settings.port,
                            access_log=False, log_level="error", proxy_headers=False)
        return 0
    except Exception:  # noqa: BLE001 - never expose credentials or backend configuration
        print('{"error":"project_runtime_unavailable"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
