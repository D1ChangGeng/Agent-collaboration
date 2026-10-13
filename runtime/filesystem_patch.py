"""Apply the common marker-based file patch format to current OS files."""
from __future__ import annotations

import os

from runtime.machine_filesystem import FilesystemError


def _update(text, lines):
    source = text.splitlines()
    output, cursor, index = [], 0, 0
    while index < len(lines):
        marker = lines[index]
        if not marker.startswith("@@"):
            raise FilesystemError("invalid_patch")
        if marker.startswith("@@ "):
            anchor = marker[3:]
            try:
                position = source.index(anchor, cursor)
            except ValueError:
                raise FilesystemError("edit_conflict") from None
            output.extend(source[cursor:position + 1])
            cursor = position + 1
        index += 1
        before, after = [], []
        while index < len(lines) and not lines[index].startswith(("@@", "***")):
            line = lines[index]
            if not line or line[0] not in {" ", "+", "-"}:
                raise FilesystemError("invalid_patch")
            if line[0] != "+":
                before.append(line[1:])
            if line[0] != "-":
                after.append(line[1:])
            index += 1
        at_end = index < len(lines) and lines[index] == "*** End of File"
        if at_end:
            index += 1
            position = len(source) - len(before)
            if position < cursor or source[position:] != before:
                raise FilesystemError("edit_conflict")
        else:
            position = cursor
        if before and not at_end:
            while position <= len(source) - len(before) and source[position:position + len(before)] != before:
                position += 1
            if position > len(source) - len(before):
                raise FilesystemError("edit_conflict")
        elif not before:
            position = len(source)
        output.extend(source[cursor:position])
        output.extend(after)
        cursor = position + len(before)
    output.extend(source[cursor:])
    ending = "\r\n" if "\r\n" in text else "\n"
    return ending.join(output) + (ending if output else "")


def apply_patch(filesystem, patch, cwd=None):
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise FilesystemError("invalid_patch")
    changes, index = [], 1
    while index < len(lines) - 1:
        header = lines[index]
        index += 1
        if header.startswith("*** Add File: "):
            action, name = "add", header[len("*** Add File: "):]
        elif header.startswith("*** Update File: "):
            action, name = "update", header[len("*** Update File: "):]
        elif header.startswith("*** Delete File: "):
            action, name = "delete", header[len("*** Delete File: "):]
        else:
            raise FilesystemError("invalid_patch")
        path = filesystem.path(name, cwd)
        destination = path
        if index < len(lines) and lines[index].startswith("*** Move to: "):
            if action != "update":
                raise FilesystemError("invalid_patch")
            destination = filesystem.path(lines[index][len("*** Move to: "):], cwd)
            index += 1
        body = []
        while index < len(lines) - 1 and not lines[index].startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ")):
            body.append(lines[index])
            index += 1
        if action == "add":
            if path.exists() or path.is_symlink() or any(not line.startswith("+") for line in body):
                raise FilesystemError("edit_conflict", path=str(path))
            original = None
            content = "\n".join(line[1:] for line in body) + ("\n" if body else "")
        else:
            original = path.read_bytes()
            content = None if action == "delete" else _update(original.decode("utf-8"), body)
        changes.append((action, path, destination, original, content))
    from runtime.filesystem_locks import locked_paths
    with locked_paths([target for change in changes for target in change[1:3]]):
        completed = []
        for offset, (action, path, destination, original, content) in enumerate(changes):
            try:
                if original is not None and path.read_bytes() != original:
                    raise FilesystemError("edit_conflict", path=str(path))
                if action == "delete":
                    path.unlink()
                elif action == "add":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("x", encoding="utf-8", newline="") as target:
                        target.write(content)
                else:
                    filesystem._write_file(path, {"content": content})
                    completed.append(str(path))
                    if destination != path:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(path, destination)
                        completed[-1] = str(destination)
                if action != "update":
                    completed.append(str(destination))
            except (OSError, FilesystemError) as error:
                code = error.code if isinstance(error, FilesystemError) else "permission_denied" if isinstance(error, PermissionError) else "filesystem_error"
                raise FilesystemError(code, completed_paths=completed,
                    pending_paths=[str(destination if str(path) in completed else path)]
                    + [str(item[1]) for item in changes[offset + 1:]]) from error
    return {"changed_paths": completed}
