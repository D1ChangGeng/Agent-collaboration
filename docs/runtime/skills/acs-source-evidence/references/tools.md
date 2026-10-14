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

## Project context and work versions

- load_project reads current instructions and knowledge indexes from the
  registered management machine/path; machine_id and management_path can
  override that read.
- configure_project updates or clears management and its document paths with
  project_id, client_request_id, expected_revision and changes.
- Owner create_work accepts omitted or null source_baseline.
- revise_work can select, change or clear source_baseline when an intent
  revision is eligible; read_resource exposes work revision history.
- submit_review and accept_work receive the commit/tree actively observed and
  reported by the Agent in source_readback, and check recorded candidate Evidence.

## Recorded Source and evidence

- list_sources discovers archived Source IDs, repository metadata and captured
  view references.
- read_source, read_source_file, list_source_files and search_source_files read
  an explicitly selected source_id and revision.
- read_diff compares base_revision and target_revision for an explicit source_id.
- list_evidence and read_resource inspect recorded claims and exact evidence.

Historical Source file results retain captured actual_source fields including
provider, root, commit, tree, view_revision and observed_at. read_source reports
the archived commit/tree, view identity and snapshot digest. Pagination continues
at that view_revision. Existing location and repository hints retain their
recorded provenance.

read_message retrieves terminal native content from Core Scope CAS. Missing
bytes use signed delivery.readback with the original Dispatch and digest.
check_inbox prepares response references. Verified historical results retain
cached Artifact identity and provenance.

The Source archive retains configured roots, normalization, tenant/Scope
ownership, revocation, secret handling, byte bounds and digest checks. Shared
mode retains the existing read_file/list_files/search_files schemas,
access/version rules and exact snapshot inputs. Machine file service access
follows the selected OS account and authenticated connection. Source reading,
execution placement, Message delivery and Git synchronization have separate
observations. Exact tool inputs follow the installed mode's active catalog.
