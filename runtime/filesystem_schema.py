"""Common file tool arguments and annotations."""
from __future__ import annotations

from runtime.machine_filesystem import TOOLS, WRITES


CONTEXT_TOOLS = frozenset({"filesystem_context", "select_filesystem"})
ALL_TOOLS = TOOLS | CONTEXT_TOOLS

FIELDS = {
    "machine_id": "string", "cwd": "string", "path": "string", "encoding": "string",
    "start_line": "integer", "end_line": "integer", "offset_bytes": "integer", "length_bytes": "integer",
    "max_output_bytes": "integer", "cursor": "string", "limit": "integer", "recursive": "boolean",
    "pattern": "string", "fixed_strings": "boolean", "case_sensitive": "boolean", "file_glob": "string",
    "content": "string", "create_parents": "boolean", "old_text": "string", "new_text": "string", "patch": "string",
}
REQUIRED = {"read_file": ["path"], "write_file": ["path", "content"],
    "edit_file": ["path", "old_text", "new_text"], "apply_patch": ["patch"], "glob": ["pattern"], "grep": ["pattern"]}
OPTIONAL = {"read_file": ["encoding", "start_line", "end_line", "offset_bytes", "length_bytes", "max_output_bytes", "cursor"],
    "list_directory": ["path", "recursive", "max_output_bytes", "limit", "cursor"],
    "glob": ["path", "max_output_bytes", "limit", "cursor"],
    "grep": ["path", "file_glob", "fixed_strings", "case_sensitive", "max_output_bytes", "limit", "cursor"],
    "write_file": ["encoding", "create_parents"], "edit_file": [], "apply_patch": [],
    "filesystem_context": [], "select_filesystem": []}
DESCRIPTIONS = {
    "read_file": "Read current text or binary file contents on the selected machine using its OS account. Paths may be absolute, relative or home-relative. Continue large reads at next_cursor.",
    "list_directory": "List current directory entries, including hidden files and links, on the selected machine.",
    "glob": "Find current filesystem paths by glob pattern on the selected machine.",
    "grep": "Search current text file contents by regular expression or literal pattern on the selected machine.",
    "write_file": "Create or replace a current file on the selected machine. Create missing parent directories by default.",
    "edit_file": "Replace one exact text match in a current file on the selected machine.",
    "apply_patch": "Apply a marker-based patch with Add File, Update File, Move to and Delete File operations on the selected machine.",
    "filesystem_context": "Read the selected filesystem machine, OS account and current directory, and discover connected machine choices.",
    "select_filesystem": "Select this session's filesystem machine and current directory. Individual file calls can override the selection.",
}


def input_schema(name):
    required = REQUIRED.get(name, [])
    optional = [*OPTIONAL[name], "machine_id", "cwd"]
    return {"type": "object", "additionalProperties": False, "required": required,
            "properties": {key: {"type": FIELDS[key]} for key in [*required, *optional]}}


def definition(name):
    return {"title": name.replace("_", " ").title(), "description": DESCRIPTIONS[name],
        "input_schema": {"required": REQUIRED.get(name, []), "optional": [*OPTIONAL[name], "machine_id", "cwd"]},
        "result_type": "filesystem", "security_scopes": [],
        "annotations": {"readOnlyHint": name not in WRITES and name != "select_filesystem",
                        "destructiveHint": name in WRITES, "idempotentHint": name not in {"edit_file", "apply_patch"}}}
