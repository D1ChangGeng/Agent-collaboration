"""Bound read-only file requests over an operator-configured forced SSH command.

SSH authenticates the admitted peer key. The private surface configuration binds
that peer to its existing ACS identity; every read rechecks that live binding.
The request never supplies a principal, Grant, Slot or executable command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.errors import AuthorizationDenied, IdentityRejected
from runtime.machine_filesystem import FilesystemError, MachineFilesystem, decode_cursor

READ_OPERATIONS = frozenset({"read_file", "filesystem_context"})


def read_request(request, filesystem, roots, authorize):
    if (not isinstance(request, dict) or set(request) != {"machine_id", "operation", "arguments"}
            or request["machine_id"] != filesystem.machine_id
            or not isinstance(request["operation"], str) or request["operation"] not in READ_OPERATIONS
            or not isinstance(request["arguments"], dict)):
        raise FilesystemError("profile_denied")
    authorize()
    args = dict(request["arguments"])
    if set(args) & {"principal_ref", "agent_slot_id", "grant_ref", "command", "executable"}:
        raise FilesystemError("invalid_argument")
    previous = decode_cursor(args["cursor"]) if args.get("cursor") else None
    if previous and (previous["machine_id"] != filesystem.machine_id or previous["action"] != request["operation"]):
        raise FilesystemError("argument_conflict")
    # Canonicalize before opening: a link into another filesystem root is not
    # admitted merely because its lexical path is inside the management tree.
    target = filesystem.path(previous["path"] if previous else args.get("path", "."),
                             previous["cwd"] if previous else args.get("cwd")).resolve()
    if not any(target == root or root.is_dir() and target.is_relative_to(root) for root in roots):
        raise FilesystemError("profile_denied")
    args["max_output_bytes"] = min(args.get("max_output_bytes", 65536), 65536)
    if request["operation"] == "filesystem_context":
        data = filesystem.context(str(target))
    else:
        args["path"] = str(target)
        data = filesystem.execute("read_file", args)
    authorize()
    return data


def main(argv=None):
    from runtime.project_schema_state import verify_project_schema
    from runtime.project_service import ProjectService
    from runtime.surface_config import configured_service

    parser = argparse.ArgumentParser(prog="acs-read-only-files")
    parser.add_argument("--config", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--read-root", action="append", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise FilesystemError("request_too_large")
        request = json.loads(raw)
        roots = [root.resolve(strict=True) for root in args.read_root]
        with configured_service(args.config) as (service, settings):
            if service.authority.access_mode != "owner":
                raise FilesystemError("profile_denied")
            verify_project_schema(service.authority)
            projects = ProjectService(service, json.loads(args.catalog.read_bytes()), profile=args.profile)

            def authorize():
                service.authenticate(settings.credential())
                with service.authority.transaction() as (authority, connection), connection.cursor() as cursor:
                    projects._authorize(authority, cursor, args.project_id, "load_project", {"project_id": args.project_id})

            filesystem = MachineFilesystem(args.machine_id, cwd=args.cwd)
            data = read_request(request, filesystem, roots, authorize)
            result = {"ok": True, "data": data}
    except FilesystemError as error:
        result = {"ok": False, "error": {"code": error.code}}
    except (AuthorizationDenied, IdentityRejected, PermissionError):
        result = {"ok": False, "error": {"code": "revoked"}}
    except Exception:  # noqa: BLE001 - private backend configuration stays private.
        result = {"ok": False, "error": {"code": "filesystem_service_unavailable"}}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
