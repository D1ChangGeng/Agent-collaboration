# Source and evidence model

SourceBinding links Project Scope to an admitted Node filesystem, Git
repository, hosted workspace or external provider. It records provider
identity, configured roots, capabilities and binding revision.

Owner current workspace views capture the admitted files actually present,
including tracked edits and untracked files. A workspace view revision
identifies their exact bytes and modes separately from repository commit and
tree. A named view is immutable; a later current read can capture newer
workspace state. Committed snapshots remain available.

SourceBaseline records repository identity, commit, tree, workspace view,
dirty and untracked manifests, and applicable submodule, LFS and environment
facts. Source synchronization records fetch, pull, push and receiver action
separately from Message delivery.

ArtifactRef identifies immutable bytes. Evidence records a claim, provenance,
scope and supporting references. ExecutionReceipt records an observed
execution. Deterministic storage and digests preserve their identities; a hash
alone establishes byte integrity.

Terminal native response Artifacts can be transferred from Receiver Scope
storage into Core's corresponding configured Scope CAS. Signed delivery.readback
chunks bind the original Dispatch, Node identity, response digest, offset and
size. Core validates the complete SHA-256 before storing the copied bytes.
The cached Artifact retains its recorded terminal receipt or fenced_late
observation and native provenance. Historical response entries expose the
original Attempt/Dispatch, result and digest; chunk retrieval selects that exact
dispatch_id. Current task and receipt lineage remain separate recorded state.

Historical execution, Artifact and Review facts keep their recorded source,
author and timestamps after natural expiry of an earlier Grant. Current access
checks explicit revocation and active object identity; current source or
readiness claims require new observation.

Large content uses a verified Artifact reference with digest and media type.
Secret values remain in their secret authority; source paths and byte bounds
apply to both workspace views and fixed snapshots.
