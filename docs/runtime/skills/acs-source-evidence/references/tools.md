# Source and evidence tool map

- list_sources discovers admitted SourceBindings and provider capabilities.
- list_files and search_files discover normalized provider paths.
- read_file returns bounded content or a verified Artifact reference.
- read_source reports repository, branch, commit, tree, workspace view and
  observed synchronization state.
- read_diff compares exact named source or workspace revisions.
- list_evidence discovers Evidence and Artifact handles.
- read_resource reads exact evidence detail.
- apply_patch, create_branch, commit_changes and push_changes use the optional
  Source-write surface when the active service exposes it.

In owner mode omitting a source revision requests the current admitted
workspace view. Keep the returned view revision and actual commit/tree with
the result. Supplying a fixed revision reads its captured bytes. The active
tool schema defines revision selection and provider bounds.

read_message uses recorded response handles to read terminal native result
content from Core's matching Scope CAS. Owner response preparation copies
missing bytes through signed delivery.readback chunks after preliminary Project
authorization completes; the formal read checks current access and digest
integrity. check_inbox prepares the same result references for its response
follow-ups. Already copied historical responses use the verified Core cache.

Reads still enforce configured roots, normalized paths, tenant and Scope
ownership, explicit revocation, secret handling, byte limits and digest
readback. External repository MCP can supply committed reads while ACS keeps
Project, WorkItem, baseline and synchronization lineage.
