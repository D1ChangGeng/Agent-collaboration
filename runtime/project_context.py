"""Current project management documents read through machine filesystem tools."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PureWindowsPath

from runtime.errors import NotFound, RevisionConflict
from runtime.machine_filesystem import FilesystemError
from runtime.project_common import canonical, parse_handle


def context_path(value):
    return PureWindowsPath(value) if PureWindowsPath(value).drive else Path(value)


class CurrentProjectContext:
    def _configure_project(self, authority, cursor, project, command, args, _credential):
        if authority.access_mode != "owner":
            raise ValueError("current-file project configuration requires the owner service")
        if args["expected_revision"] != project[2]:
            raise RevisionConflict(args["project_id"], args["expected_revision"], project[2])
        changes = args["changes"]
        allowed = {
            "management",
            "instruction_paths",
            "knowledge_index_paths",
            "skill_catalog",
            "management_identity",
        }
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("configure the management file location and document paths")
        manifest = {key: value for key, value in project[3].items() if key in allowed}
        manifest.update(changes)
        management = manifest.get("management")
        if management is not None and (
            not isinstance(management, dict)
            or set(management) - {"mode", "machine_id", "path"}
            or management.get("mode") != "current_files"
            or not isinstance(management.get("path"), str)
            or not isinstance(management.get("machine_id", "local"), str)
        ):
            raise ValueError("management location requires a current-files path")
        if management is None:
            manifest.pop("management", None)
        for field in ("instruction_paths", "knowledge_index_paths"):
            values = manifest.get(field, [])
            if (
                not isinstance(values, list)
                or len(values) > 32
                or any(not isinstance(value, str) for value in values)
            ):
                raise ValueError("document paths must be a bounded text list")
        cursor.execute(
            "UPDATE collaboration_projects SET context_manifest=%s,revision=revision+1 "
            "WHERE tenant_id=%s AND project_id=%s",
            (canonical(manifest), self.context.tenant_id, args["project_id"]),
        )
        result = self._management_record(
            authority,
            cursor,
            command,
            args,
            target_kind="project",
            target_id=args["project_id"],
            state="project.configured",
            revision=project[2] + 1,
        )
        return (
            "configured",
            {
                "project_id": args["project_id"],
                "revision": project[2] + 1,
                "operation_id": result.operation_id,
            },
            [],
        )

    def _management_location(self, cursor, project_id, manifest):
        management = manifest.get("management", {})
        if management.get("mode") == "current_files":
            return management.get("machine_id", "local"), management.get("path"), None
        # Adopt the location of an older context record, while reading its
        # current OS files rather than its recorded version or byte inventory.
        original = manifest.get("local_management_root") or manifest.get(
            "management_snapshot", {}
        ).get("original_management_root")
        if original:
            if sys.platform.startswith("linux") and PureWindowsPath(original).drive:
                value = PureWindowsPath(original)
                original = "/mnt/" + value.drive[0].lower() + "/" + "/".join(value.parts[1:])
            prefix = manifest.get("management", {}).get("path", "")
            parts = Path(prefix).parts if prefix not in {"", "."} else ()
            base = Path(original)
            for _ in parts:
                base = base.parent
            return "local", original, str(base)
        base = None
        relative = management.get("path", "")
        if not base and management.get("source_id"):
            cursor.execute(
                "SELECT p.snapshot_json,s.repository_identity FROM collaboration_source_snapshots p "
                "JOIN collaboration_sources s USING(tenant_id,project_id,source_id) "
                "WHERE s.tenant_id=%s AND s.project_id=%s AND s.source_id=%s "
                "AND p.source_commit=s.current_commit",
                (self.context.tenant_id, project_id, management["source_id"]),
            )
            row = cursor.fetchone()
            if row and row[1].get("original_management_root"):
                original = row[1]["original_management_root"]
                if sys.platform.startswith("linux") and PureWindowsPath(original).drive:
                    value = PureWindowsPath(original)
                    original = "/mnt/" + value.drive[0].lower() + "/" + "/".join(value.parts[1:])
                parts = Path(relative).parts if relative not in {"", "."} else ()
                base = Path(original)
                for _ in parts:
                    base = base.parent
                return "local", original, str(base)
            if row and row[1].get("purpose") != "management-only-snapshot":
                base = row[0].get("repository_root")
        return "local", str(Path(base) / relative) if base else None, base

    def _hydrate_current_context(self, authority, cursor, project, command, args, data):
        manifest = data["manifest"]
        route_missing = False
        if args.get("route_handle"):
            route_id = parse_handle(args["route_handle"], "route", args["project_id"])
            cursor.execute(
                "SELECT definition->'context_manifest' FROM collaboration_routes "
                "WHERE tenant_id=%s AND project_id=%s AND route_id=%s",
                (self.context.tenant_id, args["project_id"], route_id),
            )
            selected = cursor.fetchone()
            if selected is None:
                raise NotFound("route", route_id)
            if selected[0]:
                manifest = selected[0]
            else:
                route_missing = True
        machine, directory, legacy_base = self._management_location(
            cursor, args["project_id"], manifest
        )
        saved_machine = machine
        machine = args.get("machine_id") or machine
        if args.get("management_path"):
            directory = args["management_path"]
        elif args.get("machine_id") and machine != saved_machine:
            directory = self.filesystems.execute("filesystem_context", {"machine_id": machine})[
                "cwd"
            ]
        if legacy_base and (args.get("management_path") or machine != saved_machine):
            prefix = manifest.get("management", {}).get("path", "")
            base = context_path(directory)
            for _ in Path(prefix).parts if prefix not in {"", "."} else ():
                base = base.parent
            legacy_base = str(base)
        maximum = args.get("max_inline_bytes", 65536)
        if type(maximum) is not int or not 4096 <= maximum <= 1024 * 1024:
            raise ValueError("invalid project context byte budget")
        if args.get("context_view", "root_management") not in {
            "root_management",
            "route_management",
            "reviewer",
            "finalizer",
        }:
            raise ValueError("invalid project context view")
        include = set(
            args.get("include", ["root", "routes", "instructions", "knowledge_indexes", "policies"])
        )
        allowed = {
            "root",
            "routes",
            "instructions",
            "knowledge_indexes",
            "source_bindings",
            "policies",
        }
        if include - allowed:
            raise ValueError("invalid project context include")
        data["source_guidance"] = {
            "reader": "machine_filesystem",
            "version_selection": "agent_explicit",
        }
        data["manifest"] = {
            key: value
            for key, value in manifest.items()
            if key
            in {
                "instruction_paths",
                "knowledge_index_paths",
                "skill_catalog",
                "route_path",
                "management_identity",
            }
        }
        data["manifest"]["management"] = {
            "mode": "current_files",
            "machine_id": machine,
            "path": directory,
        }
        data["management_root"] = {"machine_id": machine, "path": directory}
        data["missing_context"] = ["route_management_location"] if route_missing else []
        data["instructions"], data["knowledge_indexes"], data["skills"] = [], [], []
        follow = []
        if not directory:
            data["missing_context"].append("management_location")
        used = len(json.dumps(data, ensure_ascii=False).encode())
        for label, key in (
            ("instructions", "instruction_paths"),
            ("knowledge_indexes", "knowledge_index_paths"),
        ):
            if label not in include or not directory:
                continue
            for path in manifest.get(key, []):
                selected = str(context_path(legacy_base) / path) if legacy_base else path
                arguments = {
                    "machine_id": machine,
                    "cwd": directory,
                    "path": selected,
                    "max_output_bytes": min(maximum, 65536),
                }
                try:
                    observed = self.filesystems.execute("read_file", arguments)
                except FilesystemError as error:
                    data["missing_context"].append(path)
                    data[label].append({"path": path, "error": error.code})
                    continue
                entry = {
                    "path": path,
                    "machine_id": machine,
                    "resolved_path": observed["resolved_path"],
                    "observed_at": observed["observed_at"],
                }
                payload = observed["content"].encode("utf-8")
                if observed.get("complete") and used + len(payload) + 2048 < maximum:
                    entry.update(
                        content=observed["content"], sha256=hashlib.sha256(payload).hexdigest()
                    )
                    used += len(json.dumps(entry).encode())
                else:
                    data["missing_context"].append(path)
                    action = {"rel": "read_" + label, "tool": "read_file", "arguments": arguments}
                    entry["read"] = action
                    follow.append(action)
                data[label].append(entry)
        skill_catalog = manifest.get("skill_catalog")
        if skill_catalog and directory:
            selected = (
                str(context_path(legacy_base) / skill_catalog["path"])
                if legacy_base
                else skill_catalog["path"]
            )
            try:
                result = self.filesystems.execute(
                    "read_file",
                    {
                        "machine_id": machine,
                        "cwd": directory,
                        "path": selected,
                        "max_output_bytes": 65536,
                    },
                )
                catalog = json.loads(result["content"])
                if not result.get("complete") or not isinstance(catalog.get("skills"), dict):
                    raise ValueError("Skill catalog requires a complete current read")
                for name, spec in list(catalog["skills"].items())[:64]:
                    data["skills"].append({"name": name, "description": spec["description"]})
                if "acs-project-context" in catalog["skills"]:
                    skill_path = str(
                        context_path(result["resolved_path"]).parent
                        / catalog["skills"]["acs-project-context"]["spec"]
                    )
                    follow.append(
                        {
                            "rel": "read_skill",
                            "skill": "acs-project-context",
                            "tool": "read_file",
                            "arguments": {"machine_id": machine, "path": skill_path},
                        }
                    )
            except (FilesystemError, ValueError, KeyError, TypeError):
                data["missing_context"].append("skill_catalog")
        if "source_bindings" in include:
            data["recorded_sources"] = self._list_sources(
                authority, cursor, project, command, args, None
            )[1]["items"]
        data["access_mode"] = "owner"
        data["identity_summary"] = {
            "subject": self.context.principal_ref,
            "lifetime": "until_explicit_change",
        }
        while len(canonical(data).encode()) > maximum:
            candidates = [
                entry
                for label in ("instructions", "knowledge_indexes")
                for entry in data[label]
                if "content" in entry
            ]
            if not candidates:
                raise ValueError("project metadata exceeds requested context bound")
            selected = max(candidates, key=lambda entry: len(canonical(entry).encode()))
            selected.pop("content")
            action = {
                "rel": "read_management_document",
                "tool": "read_file",
                "arguments": {
                    "machine_id": selected["machine_id"],
                    "path": selected["resolved_path"],
                    "max_output_bytes": min(maximum, 65536),
                },
            }
            selected["read"] = action
            data["missing_context"].append(selected["path"])
            follow.append(action)
        data["context_completeness"] = "partial" if data["missing_context"] else "current"
        if len(canonical(data).encode()) > maximum:
            raise ValueError("project metadata exceeds requested context bound")
        return data["context_completeness"], data, follow
