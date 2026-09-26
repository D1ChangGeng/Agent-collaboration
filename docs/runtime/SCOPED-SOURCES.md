# Multi-project and Route Source providers

Surface configuration retains the existing optional `artifacts` provider and
adds `additional_artifacts`, a bounded list with the same shape. Each entry has
one explicit `scope_id`, absolute CAS `root`, authorized Source roots and byte
limit. Scope IDs must be unique; CAS directories must be disjoint. The underlying
store also keeps its immutable on-disk `.scope` binding. No lookup falls back to
another provider when a Scope, digest or path is unavailable.

The Domain remains the authorization authority. `ScopedArtifactStores` selects
only by the complete typed reference's Scope, then delegates integrity and
filesystem checks to the existing CAS. Source capture chooses the explicitly
configured reader for the requested Scope, after current Grant/Source checks.
It requires an exact clean commit/tree and retains the existing secret exclusions.
The private Git view preserves index timestamps so Git's racy-clean detection
continues to work. A captured HEAD-relative byte/mode diff independently marks a
snapshot dirty and rejects clean-only admission, even if a stat-based status
observation missed the edit. See [Git's racy-index explanation](https://git-scm.com/docs/racy-git).
Multiple Scope providers may intentionally authorize the same checkout; their
exports and immutable artifact namespaces remain separate.

Project-scoped `source_id` values can repeat in different Projects. Source
admission resolves the target project's existing membership/Route Grant, keeps
the original authenticated caller as its authority anchor, and records the
selected scoped command. Scope, Root, Route and repository identity cannot be
silently replaced on an existing SourceBinding. Those identities and capture
bounds enter dedup. Typed Source reads resolve the stored snapshot's Scope before
selecting authority and provider; a body-supplied project name never enlarges
access.

A Root manager can admit a separate snapshot for a Route, then submit
`update_route` with `changes.context_manifest`. Its closed fields are:

- `management`: `source_id` and logical Management Root `path`;
- `instruction_paths`: bounded exact paths in the admitted snapshot;
- optional `knowledge_index_paths`;
- optional `skill_catalog`: `source_id` and `path` in the same snapshot.
- optional `route_path`: a logical Route directory for direct registry/identity
  readback and recorded adoption of an existing Git Route.

Admission reads back the real Project/Root identity bytes. A Route manager's
context then includes only its admitted Source, actual instruction/index
content, metadata-first Skill routing and bounded follow-ups. Root Source access
is not granted by Route membership; using Root documents requires an explicit
Route-scoped export. Changed/missing Source observations remain stale/partial.

PostgreSQL/Git/CAS tests establish two-project isolation with repeated Source
names, selective Grant revocation, refusal of cross-store fallback, immutable
Source identity and scoped context hydration. The guarded installer now registers
existing clean Git Roots/Routes with a reviewed plan digest; see
[project adoption](PROJECT-ADOPTION.md). Creating new Git Route directories from
Runtime intents and frozen live Harness/web workflow acceptance remain separate
pending work.
