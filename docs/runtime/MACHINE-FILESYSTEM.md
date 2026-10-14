# Machine filesystem tools

Status: accepted owner product contract. Installed code, configuration and
verification evidence establish the available transports and deployment.

ACS provides file operations on a selected machine under its connected OS
account. Start with `filesystem_context`, then call `read_file` with a path
or use the other file tools for discovery, search and changes.

## Machine, account and directory

Each MCP service instance retains its own selected machine and a working
directory for each selected machine. The installation default is `local`;
its default directory is the service account's home. Trusted
`SurfaceSettings.filesystem` can configure `default_machine_id`, `cwd`
and `ssh_machines`.

`local` means the OS and account running Core. A Core running in WSL uses the
WSL account and filesystem. A connected machine uses the OS account running its
file service. `filesystem_context` reports the actual `machine_id`,
`account`, `platform`, `home` and `cwd`, plus available machine choices.

`select_filesystem` sets the selected machine and its directory for this MCP
instance. Every file tool also accepts optional `machine_id` and `cwd` for
one call. Relative paths and directories resolve on the target machine;
`~` uses that account's home. Absolute paths, parent directories, symlinks,
Windows drive paths and UNC paths follow the target OS.

Owner access covers every path allowed by the selected OS account's
permissions, including hidden, ignored and untracked files and paths outside
repositories. Account or container isolation implements an installation's
selected access boundary.

```json
{"tool":"filesystem_context","arguments":{}}
{"tool":"select_filesystem","arguments":{"machine_id":"build-linux","cwd":"~/work"}}
{"tool":"read_file","arguments":{"path":"../notes.txt"}}
{"tool":"read_file","arguments":{"machine_id":"local","path":"~/logs/build.log"}}
```

## File operations

| Tool | Required arguments | Options and behavior |
|---|---|---|
| `read_file` | `path` | `encoding="auto"`; optional line or byte range |
| `list_directory` | none | `path="."`, `recursive=false`; returns directory entries |
| `glob` | `pattern` | `path="."`; matches paths under the search root |
| `grep` | `pattern` | `path="."`; regular expression by default, optional `file_glob`, `fixed_strings=false`, `case_sensitive=true` |
| `write_file` | `path`, `content` | Creates or overwrites; `encoding="utf-8"` or `"base64"`, `create_parents=true` |
| `edit_file` | `path`, `old_text`, `new_text` | UTF-8 text; replaces one exact match |
| `apply_patch` | `patch` | `*** Begin Patch` format with Add File, Update File, Move to and Delete File |

Read, list, glob and grep accept `max_output_bytes` and `cursor`.
List, glob and grep also accept a positive `limit`. All seven actions accept
the same optional machine and directory arguments. The public schema expresses
the file action; trusted service context supplies identity and connection data.

The owner `read_file` MCP input schema is:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["path"],
  "properties": {
    "path": {"type": "string"},
    "machine_id": {"type": "string"},
    "cwd": {"type": "string"},
    "encoding": {"type": "string"},
    "start_line": {"type": "integer"},
    "end_line": {"type": "integer"},
    "offset_bytes": {"type": "integer"},
    "length_bytes": {"type": "integer"},
    "max_output_bytes": {"type": "integer"},
    "cursor": {"type": "string"}
  }
}
```

Text lines begin at 1 and `end_line` is inclusive. Byte offsets begin at 0
and `length_bytes` counts original file bytes. Choose either a line range or
a byte range; a byte range returns Base64. `encoding="auto"`
selects UTF-8 text or Base64 binary content. Explicit `utf-8` and `base64`
are available.

```json
{"tool":"read_file","arguments":{"path":"src/main.py","start_line":10,"end_line":40}}
{"tool":"read_file","arguments":{"path":"image.png","offset_bytes":0,"length_bytes":4096}}
{"tool":"glob","arguments":{"pattern":"**/*.py","path":"~/work"}}
{"tool":"grep","arguments":{"pattern":"TODO","path":"~/work","fixed_strings":true}}
{"tool":"edit_file","arguments":{"path":"config.txt","old_text":"mode=dev","new_text":"mode=prod"}}
```

## Delivery and continuation

`max_output_bytes` controls the delivered content or entries. Text is measured
in UTF-8 bytes and binary content in encoded Base64 bytes. Local delivery
defaults to 32 KiB; a connected transport applies its current delivery budget.
The response reports the effective budget. File size and the requested search
range determine the work being read; the budget determines each delivered page.

A partial result has `complete=false` and `next_cursor`. Continue with the
returned absolute path and cursor, or use the result's `next` follow-up.
Text continuation preserves UTF-8 character boundaries and advances through
long lines. Decode each Base64 page and concatenate its bytes.

The cursor retains the original operation, machine, directory, path and query.
Changing the session selection preserves that continuation target. Conflicting
explicit continuation arguments return `argument_conflict`. A file read
whose identity changes between pages returns `file_changed`.

## Results and errors

MCP results use `acs-mcp-result/3` with `result_type="filesystem"`.
Successful file data reports `machine_id`, `account`, absolute `path`,
`resolved_path` and `observed_at` alongside the actual context.

| Action | Result data |
|---|---|
| Read | `content`, `encoding`, `offset_bytes`, `length_bytes`, `size_bytes`, `complete`, `next_cursor`, `max_output_bytes` |
| List or glob | `entries` with path, relative path, kind, size and link information; `complete`, `next_cursor`, `max_output_bytes` |
| Grep | `entries` with path, line and content; `skipped`, `complete`, `next_cursor`, `max_output_bytes` |
| Write or edit | `written_bytes`, `changed_paths` |
| Patch | `changed_paths`; a partial failure identifies `completed_paths` and `pending_paths` |

Traversal follows directories and ordinary links, tracks visited directory
identities and reports unavailable entries. Grep reports skipped binary or
unreadable files; `read_file` can retrieve binary bytes. Matches and skipped-file
diagnostics share the output budget and entry limit. Both collections paginate;
continue until `complete=true` to finish the scan.

Errors report the actual boundary: `not_found`, `permission_denied`,
`not_directory`, `is_directory`, `machine_offline`,
`authentication_failed`, `revoked`, `edit_conflict`,
`file_changed`, `argument_conflict`, `write_uncertain` or an argument/encoding
error. An exact edit requires one nonempty match.

## Writes, patches and recovery

An ordinary file write prepares complete contents in a temporary file beside
the target, preserves existing mode bits where available, then replaces the
target through the OS. Symlinks and hardlinks use native opening semantics,
retaining their target or shared inode. Account permissions govern both forms.

Service processes addressing the same resolved path share OS file locks for
changes. The OS releases these locks when their handles close or the process
exits. Exact edits read and check the content while holding the target lock.
Detected content changes return `edit_conflict`; external writers follow the
target OS's file semantics.

A patch hunk with `*** End of File` matches the file suffix. A suffix mismatch
returns `edit_conflict`. Patch changes hold the affected path locks and report
completed and pending paths when a later file action fails.

A remote write can return `write_uncertain` after dispatch if its connection
fails before a result is confirmed. Read back the affected path on the original
machine before choosing a further write. The Node request journal retains
completed receipts and identifies an interrupted write for recovery.

## Project context and file locations

Owner project registration records the machine and directory containing current
management documents. The directory may be in Git or another location accessible
to its OS account. `load_project` uses the same machine file backend to read
configured instruction and knowledge index paths. Results carry observed paths,
timestamps and content hashes. Partial context identifies unavailable documents;
larger documents supply `read_file` follow-ups.

`configure_project` updates `management`, `instruction_paths` and
`knowledge_index_paths` using `project_id`, `client_request_id` and the current
`expected_revision`. A location has `mode: current_files`, `machine_id` and
`path`; `management: null` clears the saved location. A single `load_project`
call can override `machine_id` and `management_path` for its read. Everyday
inspection and changes use the file operations described above.

The Agent chooses the reader and source version appropriate to the work.
Owner `WorkItem.source_baseline` may be omitted or null, and `revise_work`
can select, change or clear that version when the WorkItem is eligible for an
intent revision. For Review and acceptance, the Agent reports the commit/tree
actually observed through Git, native tools or machine files. Recorded candidate
Evidence retains the source facts and bytes supporting the claim.

## Connections and recorded Source history

Local, SSH and Node transports use the portable OS file backend. SSH runs an
installed fixed service argument vector and passes the structured request on
stdin. Node uses the registered Receiver's pinned TLS, signed identity, active
owner authorization, revocation checks and request journal. File requests go
directly to this service, whose readiness is independent of native Harness
Session activity.

Existing SourceBinding records and captured Source versions remain available
as an explicit archive. `list_sources` discovers recorded IDs and view
references. Select `source_id` and `revision` when reading through
`read_source_file`, `list_source_files`, `search_source_files` or `read_source`.
`read_diff` selects `source_id` with `base_revision` and `target_revision`.
Their captured `view_revision`, commit, tree and byte digests retain the
identity of the historical material.

| Reader | Selection and continuation |
|---|---|
| Machine file tools | Selected machine/account/directory; OS paths; `next_cursor` retains the actual target |
| Recorded Source tools | Explicit Source ID and captured revision; `view_revision` retains archived byte identity |

Shared installations retain the existing Source `read_file`, `list_files`
and `search_files` schemas and their configured identity, Grant, Policy and
isolation. The machine filesystem catalog is enabled for owner access.

See [Owner Runtime](OWNER-RUNTIME.md) for Project context and acceptance, and
[the adoption contract](UPGRADE-CONTRACT.md) for authority, migration and evidence.
