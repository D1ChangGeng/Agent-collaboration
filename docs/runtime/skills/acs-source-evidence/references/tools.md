# Source and evidence tool map

- list_sources discovers SourceBindings and capabilities.
- list_files and search_files discover provider paths.
- read_file returns bounded content or Artifact reference.
- read_source returns repository, branch, commit, tree, worktree, push and sync.
- read_diff compares exact revisions.
- list_evidence discovers Evidence and Artifact handles.
- read_resource reads exact evidence detail.
- apply_patch, create_branch, commit_changes and push_changes require the
  optional Source-write Profile.

External GitHub MCP can provide repository reads while ACS retains Project,
WorkItem, baseline and synchronization lineage.
