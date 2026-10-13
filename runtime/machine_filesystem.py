"""Portable current-file operations under the executing OS account."""
from __future__ import annotations

import base64
import fnmatch
import getpass
import json
import os
import platform
import re
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class FilesystemError(ValueError):
    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code, self.details = code, details


TOOLS = frozenset({"read_file", "list_directory", "glob", "grep", "write_file", "edit_file", "apply_patch"})
WRITES = frozenset({"write_file", "edit_file", "apply_patch"})


def positive(value, default):
    value = default if value is None else value
    if type(value) is not int or value < 1:
        raise FilesystemError("invalid_argument")
    return value


def encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()


def decode_cursor(value):
    try:
        result = json.loads(base64.urlsafe_b64decode(value))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError):
        raise FilesystemError("invalid_cursor") from None


class MachineFilesystem:
    def __init__(self, machine_id="local", *, cwd=None, output_bytes=32768):
        self.machine_id = machine_id
        self.cwd = str(Path(cwd or Path.home()).expanduser().absolute())
        self.output_bytes = positive(output_bytes, 32768)
        self._lock = threading.RLock()

    def context(self, cwd=None, base_cwd=None):
        selected = self.path(cwd, base_cwd) if cwd is not None else self.path(".", base_cwd)
        if cwd is not None and not selected.is_dir():
            raise FilesystemError("not_directory", path=str(selected))
        return {"machine_id": self.machine_id, "account": getpass.getuser(),
                "platform": platform.system(), "home": str(Path.home()), "cwd": str(selected),
                "access": "os_account"}

    def path(self, value, cwd=None):
        if not isinstance(value, str) or not value or "\0" in value:
            raise FilesystemError("invalid_argument")
        root = Path(cwd or self.cwd).expanduser()
        if not root.is_absolute():
            root = Path(self.cwd) / root
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        return Path(os.path.abspath(path))

    def execute(self, name: str, arguments: dict[str, Any]):
        if name not in TOOLS:
            raise FilesystemError("invalid_operation")
        args = dict(arguments)
        previous = decode_cursor(args["cursor"]) if args.get("cursor") else None
        if previous:
            if previous.get("action") != name:
                raise FilesystemError("argument_conflict")
            if args.get("cwd") is not None and str(self.path(".", args["cwd"])) != previous["cwd"]:
                raise FilesystemError("argument_conflict", field="cwd")
            if args.get("machine_id") not in (None, self.machine_id):
                raise FilesystemError("argument_conflict")
            if args.get("path") and str(self.path(args["path"], previous.get("cwd"))) != previous["path"]:
                raise FilesystemError("argument_conflict")
            for key, value in previous["query"].items():
                if key in args and args[key] != value:
                    raise FilesystemError("argument_conflict", field=key)
                args[key] = value
            args["path"] = previous["path"]
            args["cwd"] = previous["cwd"]
        path = self.path(args.get("path", "."), args.get("cwd"))
        maximum = positive(args.get("max_output_bytes"), self.output_bytes)
        try:
            if name == "apply_patch":
                from runtime.filesystem_patch import apply_patch
                with self._lock:
                    data = apply_patch(self, args["patch"], args.get("cwd"))
            elif name in WRITES:
                from runtime.filesystem_locks import locked_paths
                with self._lock, locked_paths([path]):
                    data = getattr(self, "_" + name)(path, args)
            else:
                data = getattr(self, "_" + name)(path, args, previous, maximum)
        except FileNotFoundError:
            raise FilesystemError("not_found", path=str(path)) from None
        except PermissionError:
            raise FilesystemError("permission_denied", path=str(path)) from None
        except IsADirectoryError:
            raise FilesystemError("is_directory", path=str(path)) from None
        except NotADirectoryError:
            raise FilesystemError("not_directory", path=str(path)) from None
        except UnicodeError:
            raise FilesystemError("invalid_encoding", path=str(path)) from None
        except OSError as error:
            raise FilesystemError("filesystem_error", path=str(path), errno=error.errno) from None
        return {**self.context(), "cwd": str(self.path(".", args.get("cwd"))), "path": str(path), "resolved_path": str(path.resolve()),
                "observed_at": datetime.now(UTC).isoformat(), **data}

    @staticmethod
    def identity(info):
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]

    def _cursor(self, name, path, args, **state):
        controls = {"machine_id", "cwd", "path", "cursor", "max_output_bytes", "limit"}
        return encode_cursor({"action": name, "machine_id": self.machine_id,
            "cwd": str(self.path(".", args.get("cwd"))), "path": str(path),
            "query": {k: v for k, v in args.items() if k not in controls}, **state})

    def _read_file(self, path, args, previous, maximum):
        encoding = args.get("encoding", "auto")
        if encoding not in {"auto", "utf-8", "base64"}:
            raise FilesystemError("invalid_encoding")
        byte_range = "offset_bytes" in args or "length_bytes" in args
        if byte_range and ("start_line" in args or "end_line" in args):
            raise FilesystemError("argument_conflict")
        if byte_range and encoding == "utf-8":
            raise FilesystemError("argument_conflict")
        with path.open("rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise FilesystemError("unsupported_file_type", path=str(path))
            identity = self.identity(info)
            if previous and previous.get("identity") != identity:
                raise FilesystemError("file_changed", path=str(path))
            if previous:
                encoding = previous["encoding"]
                offset, line = previous["offset"], previous["line"]
                end_offset = previous.get("end_offset")
            else:
                line = 1
                offset = args.get("offset_bytes", 0)
                if type(offset) is not int or offset < 0:
                    raise FilesystemError("invalid_argument")
                length = args.get("length_bytes")
                if length is not None and (type(length) is not int or length < 0):
                    raise FilesystemError("invalid_argument")
                end_offset = offset + length if length is not None else None
                if byte_range:
                    encoding = "base64"
                elif encoding == "auto":
                    prefix = source.read(8192)
                    try:
                        # A sample can end within a UTF-8 codepoint.
                        import codecs
                        codecs.getincrementaldecoder("utf-8")().decode(prefix, final=len(prefix) < 8192)
                        encoding = "base64" if b"\0" in prefix else "utf-8"
                    except UnicodeError:
                        encoding = "base64"
                    source.seek(0)
                if encoding == "utf-8":
                    first = positive(args.get("start_line"), 1)
                    while line < first:
                        chunk = source.readline(65536)
                        if not chunk:
                            break
                        if chunk.endswith(b"\n"):
                            line += 1
                    offset = source.tell()
            source.seek(offset)
            start = source.tell()
            if encoding == "base64":
                count = maximum // 4 * 3
                if maximum < 4:
                    raise FilesystemError("output_budget_too_small")
                if end_offset is not None:
                    count = min(count, max(0, end_offset - start))
                raw = source.read(count)
                content = base64.b64encode(raw).decode()
                next_offset = source.tell()
            else:
                end_line = args.get("end_line")
                if end_line is not None and (type(end_line) is not int or end_line < 1):
                    raise FilesystemError("invalid_argument")
                chunks, size = [], 0
                while size < maximum and (end_line is None or line <= end_line):
                    chunk = source.readline(maximum - size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if chunk.endswith(b"\n"):
                        line += 1
                raw = b"".join(chunks)
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError as error:
                    if error.reason == "unexpected end of data" and error.start >= max(0, len(raw) - 4):
                        raw = raw[:error.start]
                        if not raw:
                            raise FilesystemError("output_budget_too_small") from None
                        source.seek(start + len(raw))
                        content = raw.decode("utf-8")
                    else:
                        raise
                next_offset = source.tell()
            if self.identity(os.fstat(source.fileno())) != identity:
                raise FilesystemError("file_changed", path=str(path))
            complete = (next_offset >= info.st_size or end_offset is not None and next_offset >= end_offset
                        or encoding == "utf-8" and args.get("end_line") is not None and line > args["end_line"])
            cursor = None if complete else self._cursor("read_file", path, args, offset=next_offset,
                identity=identity, encoding=encoding, line=line, end_offset=end_offset)
            return {"content": content, "encoding": encoding, "offset_bytes": start,
                    "length_bytes": len(raw), "size_bytes": info.st_size, "next_cursor": cursor,
                    "complete": complete, "truncated": not complete, "max_output_bytes": maximum}

    def _walk(self, root, recursive=True):
        if root.is_file():
            info = root.stat()
            yield root.name, root, {"path": str(root), "relative_path": root.name,
                                   "kind": "file", "size_bytes": info.st_size}
            return
        visited = set()
        stack = [(root, "", None)]
        while stack:
            directory, prefix, iterator = stack[-1]
            if iterator is None:
                info = directory.stat()
                identity = (info.st_dev, info.st_ino)
                if identity in visited:
                    stack.pop()
                    continue
                visited.add(identity)
                with os.scandir(directory) as entries:
                    iterator = iter(sorted(entries, key=lambda item: item.name))
                stack[-1] = (directory, prefix, iterator)
            entry = next(iterator, None)
            if entry is None:
                stack.pop()
                continue
            path = Path(entry.path)
            rel = prefix + entry.name
            try:
                info = entry.stat()
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "special"
                yield rel, path, {"path": str(path), "relative_path": rel, "kind": kind,
                    "is_symlink": entry.is_symlink(), "size_bytes": info.st_size}
                if recursive and kind == "directory":
                    # Check access here so one unavailable subtree remains a
                    # reported entry rather than ending the entire search.
                    with os.scandir(path):
                        pass
                    stack.append((path, rel + "/", None))
            except (OSError, ValueError) as error:
                yield rel, path, {"path": str(path), "relative_path": rel, "kind": "unavailable",
                    "error": "permission_denied" if isinstance(error, PermissionError) else "not_available"}

    @staticmethod
    def _glob_match(path, pattern):
        parts, patterns = path.split("/"), pattern.split("/")
        positions = {0}
        for pattern_part in patterns:
            if pattern_part == "**":
                positions = set(range(min(positions), len(parts) + 1)) if positions else set()
            else:
                positions = {index + 1 for index in positions if index < len(parts)
                             and fnmatch.fnmatchcase(parts[index], pattern_part)}
        return len(parts) in positions

    def _listing(self, action, path, args, previous, maximum):
        limit = positive(args.get("limit"), 200)
        rows, used = [], 0
        after = previous.get("after") if previous else None
        last = after
        waiting = bool(after)
        recursive = action == "glob" or args.get("recursive", False)
        for rel, _target, entry in self._walk(path, recursive):
            if waiting:
                if rel == after:
                    waiting = False
                continue
            if action == "glob" and not self._glob_match(rel, args["pattern"]):
                last = rel
                continue
            size = len(json.dumps(entry, ensure_ascii=False).encode())
            if len(rows) >= limit or used + size > maximum:
                if not rows:
                    raise FilesystemError("output_budget_too_small")
                return {"entries": rows, "complete": False,
                        "next_cursor": self._cursor(action, path, args, after=last), "max_output_bytes": maximum}
            rows.append(entry)
            used += size
            last = rel
        return {"entries": rows, "complete": True, "next_cursor": None, "max_output_bytes": maximum}

    def _list_directory(self, path, args, previous, maximum):
        return self._listing("list_directory", path, args, previous, maximum)

    def _glob(self, path, args, previous, maximum):
        return self._listing("glob", path, args, previous, maximum)

    def _grep(self, path, args, previous, maximum):
        pattern = args["pattern"]
        expression = re.compile(re.escape(pattern) if args.get("fixed_strings") else pattern,
                                0 if args.get("case_sensitive", True) else re.IGNORECASE)
        limit = positive(args.get("limit"), 200)
        rows, skipped, used = [], [], 0
        resume = previous.get("file") if previous else None
        waiting = bool(resume)

        def add(row, destination):
            nonlocal used
            size = len(json.dumps(row, ensure_ascii=False).encode())
            if len(rows) + len(skipped) >= limit or used + size > maximum:
                if not rows and not skipped:
                    raise FilesystemError("output_budget_too_small")
                return False
            destination.append(row)
            used += size
            return True

        def page(rel, offset=0, line=1):
            return {"entries": rows, "skipped": skipped, "complete": False,
                    "next_cursor": self._cursor("grep", path, args, file=rel, offset=offset, line=line),
                    "max_output_bytes": maximum}

        for rel, target, entry in self._walk(path):
            if waiting:
                if rel != resume:
                    continue
                waiting = False
            if not self._glob_match(rel, args.get("file_glob", "**/*")):
                continue
            if entry["kind"] == "unavailable":
                if not add({"path": str(target), "reason": entry["error"]}, skipped):
                    return page(rel)
                continue
            if entry["kind"] != "file":
                continue
            line = previous.get("line", 1) if previous and rel == resume else 1
            offset = previous.get("offset", 0) if previous and rel == resume else 0
            try:
                with target.open("rb") as source:
                    info = source.read(8192)
                    if b"\0" in info:
                        if not add({"path": str(target), "reason": "binary"}, skipped):
                            return page(rel)
                        continue
                    source.seek(offset)
                    while True:
                        offset = source.tell()
                        raw = source.readline()
                        if not raw:
                            break
                        text = raw.decode("utf-8")
                        if expression.search(text):
                            row = {"path": str(target), "line": line, "content": text.rstrip("\r\n")}
                            size = len(json.dumps(row, ensure_ascii=False).encode())
                            if size > maximum:
                                row["content"] = row["content"][:max(1, maximum // 4)]
                                row["truncated"] = True
                            if not add(row, rows):
                                return page(rel, offset, line)
                        line += 1
            except (OSError, UnicodeError) as error:
                if not add({"path": str(target), "reason": "permission_denied" if isinstance(error, PermissionError) else "not_text"}, skipped):
                    return page(rel, offset, line)
        return {"entries": rows, "skipped": skipped, "complete": True, "next_cursor": None, "max_output_bytes": maximum}

    def _write_file(self, path, args):
        content = args["content"]
        if args.get("encoding", "utf-8") == "base64":
            data = base64.b64decode(content, validate=True)
        elif args.get("encoding", "utf-8") == "utf-8":
            data = content.encode("utf-8")
        else:
            raise FilesystemError("invalid_encoding")
        if args.get("create_parents", True):
            path.parent.mkdir(parents=True, exist_ok=True)
        info = path.stat() if path.exists() else None
        native = path.is_symlink() or info is not None and info.st_nlink > 1
        if native:
            # Links keep their target/inode and native account semantics.
            with path.open("wb") as output:
                output.write(data)
        else:
            import tempfile
            fd, temporary = tempfile.mkstemp(prefix=".acs-write-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    if info is not None:
                        os.chmod(temporary, stat.S_IMODE(info.st_mode))
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {"written_bytes": len(data), "changed_paths": [str(path)]}

    def _edit_file(self, path, args):
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        old, new = args["old_text"], args["new_text"]
        if not old or text.count(old) != 1:
            raise FilesystemError("edit_conflict", path=str(path))
        if path.read_bytes() != raw:
            raise FilesystemError("edit_conflict", path=str(path))
        return self._write_file(path, {"content": text.replace(old, new, 1), "create_parents": False})
