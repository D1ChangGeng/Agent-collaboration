# Source and evidence model

## Current machine files and Project context

Machine filesystem tools read and change current OS files under a connected
account. Each MCP instance selects a machine and retains its directory for that
machine. filesystem_context reports actual account, home, platform and cwd.
A per-call machine_id/cwd selects that call's target; a pagination cursor retains
the original target. OS account or container permissions define access.

Owner Project registration stores its current management machine, directory and
document paths. Management Roots can reside in Git or another authorized
directory. load_project reads configured instructions and knowledge indexes
through the file backend, returning observed paths, timestamps, content hashes
and context completeness. configure_project changes or clears the saved location.
Project and Root identities survive a file-location change.

## Work versions and recorded Source history

The Agent chooses an available machine, native, Git, repository MCP or other
reader through its actual connection and access. Reading location and execution
Node/Runtime placement have separate bindings. Owner WorkItem.source_baseline
may be omitted or null, and eligible revise_work operations can select, change
or clear it. Evidence keeps the version originally observed for its candidate.

Existing SourceBinding records and captured Source views form an explicit archive.
Select source_id and revision to read historical bytes; select source_id with
base_revision and target_revision for a historical diff. Captured file results
identify provider, root, commit, tree, view_revision and observed_at; read_source
reports the archived commit/tree and view identity. Pagination retains that
view_revision. Machine results identify their current OS target,
path and observation time. Each new WorkItem's version is selected by its Agent.

## Evidence identity

Owner Review and acceptance use the commit/tree that the Agent actually observed
and actively reports through source_readback. The recorded candidate Evidence
and execution receipt must agree with that version. Relevant repository edits,
workspace state, submodule, LFS and environment facts belong to the evidence
supporting the claim. An optional WorkItem version and an Evidence record's
source provenance have separate lifecycles.

ArtifactRef identifies immutable bytes. Evidence records a claim, provenance,
scope and supporting references. ExecutionReceipt records an observed execution.
Deterministic storage and digests preserve their identities.

Terminal native response Artifacts can be copied into Core Scope CAS through
signed delivery.readback chunks. The original Dispatch, Node identity, digest,
offset and size bind the transfer; Core validates the complete SHA-256.
Historical response entries retain their original Attempt/Dispatch, result and
digest. Current task and receipt lineage have separate recorded state.

Historical execution, Artifact and Review facts retain their original source,
author and time after a prior Grant's natural expiry. Current reads apply explicit
revocation and the chosen reader's access contract; imported facts retain
provenance. Shared Scope/permission and version checks preserve their existing
contract and reference Profile. Source reading, Message delivery and Git
synchronization have separate observations.
