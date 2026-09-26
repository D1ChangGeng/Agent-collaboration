"""Bounded project Source reads from admitted snapshots and verified CAS bytes."""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
from collections.abc import Mapping
from pathlib import PurePosixPath

from runtime.data_policy import artifact_authorizer, source_authorizer
from runtime.models import ArtifactRef
from runtime.source import SourceError, SourcePathError, SourceReadbackError, SourceService
from runtime.source_models import SourceFile, SourceRequest, SourceSnapshot


class ProjectSources:
    def __init__(self, store, authorized_roots):
        self.store = store
        self.readers = {}
        try:
            if isinstance(authorized_roots, Mapping):
                for scope, roots in authorized_roots.items():
                    provider = store.for_scope(scope)
                    self.readers[scope] = SourceService(provider, roots, max_bytes=provider.max_bytes)
            else:
                self.readers[store.scope_id] = SourceService(store, authorized_roots, max_bytes=store.max_bytes)
        except BaseException:
            self.close()
            raise

    def _reader(self, scope):
        if scope not in self.readers:
            raise SourceError("Source Scope has no admitted provider")
        return self.readers[scope]

    def close(self):
        for reader in self.readers.values():
            reader.close()

    def capture(self, request, authority, command):
        if request.allow_dirty or request.include_untracked or not request.expected_commit or not request.expected_tree:
            raise ValueError("project Source binding requires an exact clean committed baseline")
        return self._reader(request.scope_id).admit(request, source_authorizer(authority, command),
                                 artifact_authorize=artifact_authorizer(authority, command))

    @staticmethod
    def snapshot(value):
        value = dict(value)
        value["files"] = tuple(SourceFile(**item) for item in value["files"])
        value["excluded_paths"] = tuple(value["excluded_paths"])
        return SourceSnapshot(**value)

    @staticmethod
    def path(value, *, root=False):
        if root and value in {"", "."}:
            return ""
        if (not isinstance(value, str) or not value or "\\" in value or ":" in value
                or any(ord(char) < 32 for char in value) or value.startswith("/")
                or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise SourcePathError("Source path must be a normalized logical path")
        return value

    @staticmethod
    def bound(value, maximum=65536, minimum=1):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Source output bound is invalid")
        return value

    def observe(self, snapshot, authority, command):
        request = SourceRequest(root=snapshot.repository_root, tenant_id=snapshot.tenant_id,
            scope_id=snapshot.scope_id, root_id=snapshot.root_id, route_id=snapshot.route_id)
        return self._reader(snapshot.scope_id).observe(request, source_authorizer(authority, command))

    def verify_current_paths(self, snapshot, paths, authority, command):
        self._reader(snapshot.scope_id).verify_current_paths(snapshot, paths, source_authorizer(authority, command))

    def verify(self, snapshot, authority, command):
        """Verify manifest provenance without reading unrelated Skill bodies."""
        authorize = source_authorizer(authority, command)
        authorize(SourceRequest(root=snapshot.repository_root, tenant_id=snapshot.tenant_id,
                  scope_id=snapshot.scope_id, root_id=snapshot.root_id, route_id=snapshot.route_id))
        reference = ArtifactRef.model_validate(snapshot.manifest_ref, strict=True)
        artifact_authorizer(authority, command)(reference, "read")
        data = self.store.read(reference)
        if hashlib.sha256(data).hexdigest() != snapshot.snapshot_sha256:
            raise SourceReadbackError("Source manifest digest changed")
        stored = json.loads(data)
        expected = snapshot.manifest_dict()
        for item in (stored, expected):
            item["manifest_ref"] = None
            item.pop("snapshot_sha256", None)
        if stored != expected:
            raise SourceReadbackError("Source manifest ownership differs")

    def file_bytes(self, snapshot, path, authority, command):
        path = self.path(path)
        self.verify(snapshot, authority, command)
        item = next((item for item in snapshot.files if item.path == path), None)
        if item is None:
            raise SourcePathError("Source file is not in the admitted manifest")
        reference = ArtifactRef.model_validate(item.artifact_ref, strict=True)
        artifact_authorizer(authority, command)(reference, "read")
        data = self.store.read(reference)
        if len(data) != item.size_bytes or hashlib.sha256(data).hexdigest() != item.sha256:
            raise SourceReadbackError("Source file digest changed")
        return data, item

    def read_file(self, snapshot, args, authority, command):
        data, item = self.file_bytes(snapshot, args["path"], authority, command)
        maximum = self.bound(args.get("max_inline_bytes", 32768))
        start = self.bound(args.get("start_line", 1), maximum=10_000_000)
        lines = data.decode("utf-8").splitlines(keepends=True)
        end = args.get("end_line", len(lines))
        if type(end) is not int or end < start - 1 or end > 10_000_000:
            raise ValueError("invalid source line range")
        content = ""
        last = start - 1
        for number in range(start, min(len(lines), end) + 1):
            candidate = content + lines[number - 1]
            if len(candidate.encode()) > maximum:
                break
            content, last = candidate, number
        truncated = last < min(len(lines), end)
        # A single oversized line cannot be paged by line number. Its verified
        # ArtifactRef remains available rather than repeating the same follow-up.
        return {"path": item.path, "revision": snapshot.source_commit,
                "sha256": item.sha256, "bytes": item.size_bytes,
                "start_line": start, "end_line": last, "total_lines": len(lines),
                "content": content, "truncated": truncated,
                "artifact_ref": dict(item.artifact_ref) if truncated else None,
                "next_start_line": last + 1 if truncated and last >= start else None}

    def list_files(self, snapshot, args, authority, command):
        self.verify(snapshot, authority, command)
        prefix = self.path(args["path"], root=True)
        prefix = prefix + "/" if prefix else ""
        depth = self.bound(args.get("depth", 1), maximum=20)
        limit = self.bound(args.get("limit", 100), maximum=100)
        entries = {}
        for item in snapshot.files:
            if not item.path.startswith(prefix):
                continue
            parts = item.path[len(prefix):].split("/")
            selected = prefix + "/".join(parts[:depth])
            entries[selected] = {"path": selected, "kind": "directory" if len(parts) > depth else "file",
                                 "revision": snapshot.source_commit}
            if len(parts) <= depth:
                entries[selected].update(bytes=item.size_bytes, sha256=item.sha256)
        cursor = args.get("cursor")
        rows = [entries[path] for path in sorted(entries) if not cursor or path > cursor]
        return {"items": rows[:limit], "next_cursor": rows[limit-1]["path"] if len(rows) > limit else None}

    def search_files(self, snapshot, args, authority, command):
        prefix = self.path(args.get("path", ""), root=True)
        prefix = prefix + "/" if prefix else ""
        query = args["query"]
        if not query or len(query) > 512:
            raise ValueError("search query must be bounded nonempty text")
        limit = self.bound(args.get("limit", 50), maximum=100)
        glob = args.get("glob", "*")
        self.verify(snapshot, authority, command)
        rows = []
        scanned = 0
        last = None
        more = False
        for item in snapshot.files:
            if (not item.path.startswith(prefix) or not fnmatch.fnmatchcase(item.path, glob)
                    or (args.get("cursor") and item.path <= args["cursor"])):
                continue
            if scanned >= 2_000_000 or len(rows) >= limit:
                more = True
                break
            # The snapshot caps individual files. Search has its own per-call
            # scan budget; a large file is still independently readable.
            if item.size_bytes > 2_000_000:
                raise SourceError("source file exceeds bounded content-search capacity")
            data, _ = self.file_bytes(snapshot, item.path, authority, command)
            scanned += len(data)
            last = item.path
            try:
                text = data.decode("utf-8")
            except UnicodeError:
                continue
            matches = [n for n, line in enumerate(text.splitlines(), 1) if query in line]
            if query in item.path or matches:
                rows.append({"path": item.path, "lines": matches[:20], "sha256": item.sha256,
                             "revision": snapshot.source_commit})
        return {"items": rows, "next_cursor": last if more else None, "scanned_bytes": scanned}

    def read_diff(self, base, target, args, authority, command):
        maximum = self.bound(args.get("max_inline_bytes", 65536))
        requested = args.get("paths")
        if requested is not None:
            requested = {self.path(path) for path in requested}
        self.verify(base, authority, command)
        self.verify(target, authority, command)
        before = {item.path: item for item in base.files}
        after = {item.path: item for item in target.files}
        paths = sorted(set(before) | set(after))
        changes = []
        content = ""
        truncated = False
        for path in paths:
            if requested is not None and path not in requested:
                continue
            old, new = before.get(path), after.get(path)
            if old and new and (old.sha256, old.mode) == (new.sha256, new.mode):
                continue
            changes.append({"path": path, "before_sha256": old.sha256 if old else None,
                            "after_sha256": new.sha256 if new else None})
            old_bytes = self.file_bytes(base, path, authority, command)[0] if old else b""
            new_bytes = self.file_bytes(target, path, authority, command)[0] if new else b""
            try:
                old_lines, new_lines = old_bytes.decode("utf-8").splitlines(True), new_bytes.decode("utf-8").splitlines(True)
                diff = "".join(difflib.unified_diff(old_lines, new_lines,
                    fromfile="a/" + path if old else "/dev/null",
                    tofile="b/" + path if new else "/dev/null"))
            except UnicodeError:
                diff = f"Binary content changed: {path}\n"
            if len((content + diff).encode()) <= maximum:
                content += diff
            else:
                truncated = True
        return {"base_revision": base.source_commit, "target_revision": target.source_commit,
                "content": content, "changes": changes, "truncated": truncated}

    @staticmethod
    def skill_spec(catalog_path, specification):
        # Skill paths in the contract are relative to that contract's directory.
        path = str(PurePosixPath(catalog_path).parent / specification)
        return ProjectSources.path(path)
