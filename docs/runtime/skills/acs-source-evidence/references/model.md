# Source and evidence model

SourceBinding links project Scope to a local Node filesystem, Git repository,
hosted workspace or external provider. It records provider identity,
capabilities, revision and freshness without copying authority.

SourceBaseline binds repository identity, commit, tree, dirty and untracked
manifest, submodule or LFS state and environment references as applicable.
ArtifactRef identifies immutable bytes. Evidence records a claim, provenance,
scope, validity and supporting handles. ExecutionReceipt records observed
execution.

Large content is returned by immutable Artifact reference with digest and media
type. Secret values remain in their secret authority.
