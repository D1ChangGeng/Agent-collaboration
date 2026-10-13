"""Per-session file context and machine selection using installed connections."""
from __future__ import annotations

import json
import subprocess
import threading

from runtime.machine_filesystem import FilesystemError, MachineFilesystem, decode_cursor


class FilesystemGateway:
    _backend_lock = threading.Lock()

    def __init__(self, authority, settings=None):
        self.authority = authority
        self.settings = settings or getattr(authority, "_filesystem_settings", None)
        # Context belongs to a connection; local file mutations share the
        # service backend so edits serialize across those connections.
        with self._backend_lock:
            if not hasattr(authority, "_filesystem_backend"):
                authority._filesystem_backend = MachineFilesystem("local", cwd=getattr(self.settings, "cwd", None))
            self.local = authority._filesystem_backend
        self.selected = getattr(self.settings, "default_machine_id", "local")
        self.directories = {"local": self.local.cwd}
        self._lock = threading.RLock()

    def machines(self):
        result = [{"machine_id": "local", "transport": "local", **self.local.context()}]
        for endpoint in self.authority._delivery_endpoints.values():
            if hasattr(endpoint, "filesystem"):
                descriptor = endpoint.descriptor()
                result.append({"machine_id": descriptor["machine_id"], "transport": "node"})
        for target in getattr(self.settings, "ssh_machines", ()):
            result.append({"machine_id": target.machine_id, "transport": "ssh"})
        return result

    def _target(self, machine_id):
        if machine_id == "local":
            return self.local
        for endpoint in self.authority._delivery_endpoints.values():
            if hasattr(endpoint, "filesystem") and endpoint.descriptor()["machine_id"] == machine_id:
                return endpoint
        for target in getattr(self.settings, "ssh_machines", ()):
            if target.machine_id == machine_id:
                return target
        raise FilesystemError("unknown_machine", machine_id=machine_id)

    def _invoke(self, machine_id, operation, arguments):
        target = self._target(machine_id)
        if target is self.local:
            return self.local.context(arguments.get("cwd"), arguments.get("base_cwd")) if operation == "filesystem_context" else self.local.execute(operation, arguments)
        if hasattr(target, "filesystem"):
            return target.filesystem(self.authority.context, operation, arguments)
        request = {"machine_id": machine_id, "operation": operation, "arguments": arguments}
        try:
            # Arguments and file content remain stdin data. The configured
            # target invokes one fixed, installed service command.
            completed = subprocess.run(["ssh", "-T", target.ssh_target, *target.service_argv],
                input=json.dumps(request), capture_output=True, text=True, timeout=60, check=False)
            if completed.returncode:
                from runtime.machine_filesystem import WRITES
                raise FilesystemError("write_uncertain" if operation in WRITES else "machine_offline", machine_id=machine_id)
            result = json.loads(completed.stdout)
            if not result["ok"]:
                error = dict(result["error"])
                code = error.pop("code")
                raise FilesystemError(code, **error)
            return result["data"]
        except subprocess.TimeoutExpired:
            from runtime.machine_filesystem import WRITES
            raise FilesystemError("write_uncertain" if operation in WRITES else "machine_offline", machine_id=machine_id) from None
        except OSError:
            raise FilesystemError("machine_offline", machine_id=machine_id) from None

    def execute(self, operation, arguments):
        args = dict(arguments)
        cursor = decode_cursor(args["cursor"]) if args.get("cursor") else None
        with self._lock:
            machine_id = args.get("machine_id") or (cursor["machine_id"] if cursor else self.selected)
            if cursor and args.get("machine_id") and args["machine_id"] != cursor["machine_id"]:
                raise FilesystemError("argument_conflict")
            base_cwd = self.directories.get(machine_id)
            cwd = cursor["cwd"] if cursor else base_cwd
        if args.get("cwd") is not None:
            normalized = self._invoke(machine_id, "filesystem_context", {"cwd": args["cwd"], "base_cwd": base_cwd})["cwd"]
            if cursor and normalized != cursor["cwd"]:
                raise FilesystemError("argument_conflict", field="cwd")
            cwd = normalized
        if operation in {"filesystem_context", "select_filesystem"}:
            info = self._invoke(machine_id, "filesystem_context", {})
            chosen = cwd or info["cwd"]
            # Validate and normalize the selected directory on the target OS.
            if operation == "select_filesystem":
                data = self._invoke(machine_id, "filesystem_context", {"cwd": chosen})
                chosen = data["cwd"]
                with self._lock:
                    self.selected = machine_id
                    self.directories[machine_id] = chosen
            return {**info, "cwd": chosen, "machines": self.machines()}
        args.pop("machine_id", None)
        if cwd:
            args["cwd"] = cwd
        return self._invoke(machine_id, operation, args)


def serve_file_request():
    import sys
    try:
        request = json.load(sys.stdin)
        filesystem = MachineFilesystem(request["machine_id"])
        operation = request["operation"]
        data = filesystem.context(request["arguments"].get("cwd"), request["arguments"].get("base_cwd")) if operation == "filesystem_context" else filesystem.execute(operation, request["arguments"])
        result = {"ok": True, "data": data}
    except FilesystemError as error:
        result = {"ok": False, "error": {"code": error.code, **error.details}}
    except (ValueError, KeyError, TypeError):
        result = {"ok": False, "error": {"code": "invalid_argument"}}
    print(json.dumps(result))


if __name__ == "__main__":
    serve_file_request()
