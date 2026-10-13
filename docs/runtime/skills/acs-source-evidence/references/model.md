# Source and evidence model

## Current machine files and repository guidance

Machine filesystem tools read and change current OS files under a connected
account. Each MCP instance selects a machine and retains its directory for that
machine. filesystem_context reports actual account, home, platform and cwd.
A per-call machine_id/cwd selects that call's target; a pagination cursor retains
the original target. OS account or container permissions define access.

SourceBinding provides a Project repository, readable-location and version hint.
The Agent chooses an available machine file, Native, Git, repository MCP or other
reader through its actual connection and access. Reading location and execution
Node/Runtime placement have separate bindings.

Explicit Source tools refer to a repository checkout or captured view.
primary_source_id identifies the Project product Source;
primary_source_root identifies its preferred repository reading location.
Current Source reads resolve the physical primary worktree and observe its
actual branch, edits and admitted untracked files. Explicit source_root selects
a configured readable current worktree; explicit revision selects captured bytes.

## Product and management observations

Owner load_project reports product source_observation and a distinct
management_source_observation. Management snapshots provide instruction and
coordination context. An unavailable product default yields null
source_observation, source_guidance.primary_source_id and
source_guidance.version_hint_ref. Explicit management reads retain their own
Source selection and access checks.

Source actual_source identifies provider, root, commit, tree, view_revision
and observed_at. Record actual repository, branch and workspace state alongside
that captured view identity. list_sources.current_readable_root reports the
Source provider's reading location; origin_hint.host/path reports repository
guidance. Machine results identify their OS target, path and observation time.

## Explicit snapshots and evidence identity

A fixed commit or captured workspace view is an explicit selection. Source
pagination keeps the returned view_revision for stable bytes. Machine reads
observe current file bytes; a changed file can invalidate their continuation.
Choose captured Source bytes for reproducible repository Review and Evidence.

SourceBaseline and Evidence retain the actual reader, repository/location,
branch, commit/tree, workspace state and view identity, plus applicable submodule,
LFS and environment facts. Review and acceptance bind the actual candidate.

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
contract. Source reading, Message delivery and Git synchronization have separate
observations.
