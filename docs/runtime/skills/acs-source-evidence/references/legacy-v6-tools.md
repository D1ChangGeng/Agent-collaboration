# Source and evidence tool map

## Current machine files

- filesystem_context discovers the selected machine, actual OS account, home,
  platform, cwd and connected choices.
- select_filesystem sets this MCP instance's default machine and directory.
- Owner read_file requires path and reads current UTF-8 or Base64 content.
- list_directory and glob find current paths; grep searches current text.
- write_file, edit_file and apply_patch change current files under OS permissions.

All file actions accept optional machine_id/cwd. A per-call selection applies to
that call. Reads and searches paginate with max_output_bytes and next_cursor;
list/search limit bounds delivered entries. Line ranges start at 1 with inclusive
end_line. Byte ranges start at 0 and return Base64. The continuation retains its
original machine, directory, path and query.

Machine result data identifies the actual account, machine, path and observed_at.
Use complete/next_cursor to finish the requested range. OS and transport failures
report their actual boundary. For an uncertain remote write, read back the target
before choosing a further action.

## Project Source and evidence

- list_sources reports repository/version hints, provider capabilities,
  current_readable_root and origin_hint.host/path.
- read_source reports observed repository/branch/workspace state and selected
  view identity; owner actual_source supplies captured readback fields.
- read_source_file, list_source_files and search_source_files read the selected
  Project Source view.
- read_diff compares two explicit captured commit or workspace revisions.
- list_evidence and read_resource inspect recorded claims and exact evidence.

Owner Source tools can omit source_id/revision while retaining project_id and
the file/query action. The service resolves the product repository Source.
primary_source_root locates its preferred physical primary checkout.
Explicit source_root selects a configured readable current worktree; revision
selects captured bytes. Source pagination retains the returned view_revision.

Owner Source results include actual_source with provider, root, commit, tree,
view_revision and observed_at. Record actual repository, branch and workspace
observations. current_readable_root describes the Source provider's location;
origin_hint.host/path remains repository guidance.

load_project.source_observation refers to product source.
management_source_observation retains distinct management context. Unavailable
product defaults leave product observation and primary/version references null.
Source follow-ups use the explicit Source tool names and preserve the selected
view where needed.

read_message retrieves terminal native content from Core Scope CAS. Missing
bytes use signed delivery.readback with the original Dispatch and digest.
check_inbox prepares response references. Verified historical results retain
cached Artifact identity and provenance.

The Source provider retains its configured roots, normalization, tenant/Scope
ownership, revocation, secret handling, byte bounds and digest checks. Shared mode
retains the existing read_file/list_files/search_files schemas, access/version
rules and exact snapshot inputs. Machine file service access follows the selected
OS account and authenticated connection. Source reading, execution placement,
Message delivery and Git synchronization have separate observations.
