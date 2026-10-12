# Source and evidence model

## Product repository guidance

SourceBinding provides a Project repository, readable-location and version hint.
The Agent chooses an available Native, Git, external repository MCP or other
reader through that tool's actual connection and access. Recommended versions
help identify context; an explicit revision selects captured bytes.

The Project primary product Source refers to a repository checkout. A declared
primary_source_id identifies that Source; primary_source_root identifies the
preferred repository reading location. Default current reads resolve its
physical primary worktree and observe the branch currently checked out there,
including current edits and admitted untracked files. Explicit source_root
selects the caller's configured readable current worktree.

Reading location and execution Node/Runtime placement have separate bindings.
Core filesystem tools expose their configured readable roots. Existing Agent
tools expose their own local or remote repository capabilities.

## Product and management observations

Owner load_project reports the product Source in source_observation and a
distinct Management Root in management_source_observation. Management snapshots
provide instruction and coordination context. A missing product default yields
null source_observation, source_guidance.primary_source_id and
source_guidance.version_hint_ref. Explicit management reads retain their own
source selection and access checks.

Owner filesystem tools can omit source_id/revision and resolve the product
default. Their actual_source identifies provider, root, commit, tree,
view_revision and observed_at. Record actual repository, branch and workspace
state alongside this captured view identity.

list_sources separates current_readable_root, the Core provider's reported
reading location, from origin_hint.host/path, repository origin guidance.
An Agent chooses its reader using actual available capability and records the
source it used.

## Explicit snapshots and evidence identity

A fixed commit or captured workspace view is an explicit selection.
Routine context follow-ups read the current view and carry version hints.
Pagination keeps the returned view_revision for stable continuation.
SourceBaseline and Evidence retain actual provider, repository/location,
branch, commit/tree, workspace state and view identity, plus applicable
submodule, LFS and environment facts. Review and acceptance bind the actual
candidate and source evidence.

ArtifactRef identifies immutable bytes. Evidence records a claim, provenance,
scope and supporting references. ExecutionReceipt records an observed
execution. Deterministic storage and digests preserve their identities.

Terminal native response Artifacts can be copied into Core Scope CAS through
signed delivery.readback chunks. The original Dispatch, Node identity, digest,
offset and size bind the transfer; Core validates the complete SHA-256.
Historical response entries retain their original Attempt/Dispatch, result and
digest. Current task and receipt lineage have separate recorded state.

Historical execution, Artifact and Review facts retain their original source,
author and time after a prior Grant's natural expiry. Current reads apply
explicit revocation and provider access; imported facts retain provenance.
Shared Scope/permission and version checks preserve their existing contract.
Source reading, Message delivery and Git synchronization remain separate facts.
