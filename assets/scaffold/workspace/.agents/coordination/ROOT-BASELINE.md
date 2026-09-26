# Root Collaboration Baseline and Route Migration Contract

Status: adopted Root baseline for ACHP workspace schema 0.2.

## Entities

- **Project Collaboration Root** — durable management/control workspace for
  project identity, Route registry, shared constraints, and coordination.
- **Development Route Node** — long-lived architecture/goal route with its own
  identity, state, knowledge, and execution relationships.
- **Execution Endpoint** — replaceable engineer/agent/session/host capacity;
  Route↔Endpoint is not a permanent 1:1 identity.
- **Source Repository / Repository State** — implementation location and
  verifiable branch/commit/tree/worktree/push/sync evidence. It may be outside
  the Root and may be unknown.

## Ownership and inheritance

Root owns stable project identity, registry, migration contract, and minimal
cross-route coordination. A Route owns its goals, route-specific AGENTS,
knowledge, state, and engineer-facing continuity. Endpoint facts are runtime
records; Source State Evidence is the claim boundary.

Routes must explicitly read this contract. Do not assume a Harness will inherit a
parent `AGENTS.md` from a non-Git management tree. Do not copy this contract or
the entire Root protocol into every Route.

## Route creation and adoption

`project_setup.py route create` creates only minimal route metadata and a concise
route router. `route adopt` registers an existing Route and preserves its
`AGENTS.md`, `.agents/knowledge/`, references, and state. A Root operation must
not recursively run repository adopt against a Route.

Registry writes are limited to stable identity, path, lifecycle, and pointers.
Per-turn status, engineer reports, and dynamic evidence remain Route-owned; any
Root aggregate is a generated view, not a second source of truth.

The canonical registry path is `routes.yaml`. In the current standard-library
implementation its contents are deterministic JSON text (also valid YAML 1.2),
so there is one registry and one spelling rather than parallel JSON/YAML sources.

### Schema 0.2 implementation boundary

The currently implemented Workspace operations are `bootstrap`, `adopt`,
`upgrade`, `repair`, and `validate`. They use the exact supplied Workspace path;
they do not require or infer a Git root. `workspace uninstall` is intentionally
guarded and currently returns a refusal without changing files until a reviewed
ownership plan exists. It is not an implemented removal workflow.

The currently implemented Route operations are `create`, `adopt`, `list`,
`validate`, `set-state`, and `rename`. Route `rename` changes only the stable
display metadata; it does not move the Route directory, change its registry path,
or rewrite Route-owned content. The Route path is therefore immutable in the
current schema 0.2 implementation.

Source Repository and Execution Endpoint fields are metadata pointers only at
this stage. They remain `unknown` until separately evidenced; their presence in
the registry does not mean that a binding or replacement operation exists.

## Source State Evidence and initial baseline

At first Route↔Endpoint contact, reuse a valid recorded baseline. If it is
missing, stale, or conflicts with reality, collect the targeted repository,
remote, branch, commit, tree, worktree, push, receiver-sync, endpoint, and
observed-at fields needed for the next action. Missing values remain `unknown`,
`unverified`, or `not-measured`. Historical paths and reports do not establish
current execution identity.

## Communication

Root↔Route communication carries only project-level decisions, dependencies,
risks, lifecycle changes, and baseline requirements. Route↔Executor keeps the
existing vertical feedback loop. Route↔Route uses minimal-necessary sync when a
fact can change the receiver's next action. Transport is selected from verified
capability; manual user forwarding is always valid.

## AGENTS and knowledge migration

Preserve existing Route `AGENTS.md`, self-evolution settings, Guides, Decisions,
Observations, references, and state until the Route's own session accepts a
migration. Root `AGENTS.md` remains concise and does not duplicate Route bodies.
Collaboration defines scope and ownership; self-evolution defines knowledge
capture, retrieval, correction, indexing, and maintenance.

## Lifecycle

The implemented metadata lifecycle is: create, adopt, validate, display rename,
and explicit state updates for `discovered`, `active`, `paused`, `completed`,
`archived`, or `legacy-unmigrated`. An `archived` value is a registry/metadata
state, not a filesystem archive operation. Returning to another state is also a
metadata edit; it is not, by itself, a restore or rollback workflow.

Path-moving rename, Endpoint replacement, Route split/merge, restore, rollback,
and Workspace uninstall remain reviewable future migration contracts. They must
not be represented as automatic graph rewrites or inferred from a display-name
change. Any future implementation must require an explicit ownership plan,
source-state evidence where applicable, dry-run output, review, and a reversible
recovery path. No reset, delete, silent path move, or silent reclassification is
allowed.

For implemented mutating commands, `--dry-run` is the review boundary and
repeated equivalent operations are intended to be idempotent. This guarantee
does not imply that the future migration contracts above are already available.

## Phase-1 boundary for existing Routes

The first Root migration registers and points to existing Routes without
performing A/B semantic migration or business work. A/B sessions later consume
this baseline and independently migrate their own route metadata, AGENTS routing,
source-state evidence, and knowledge boundaries.

## Acceptance

Root migration is complete when Root validation passes, routes are discoverable,
existing Route bytes are preserved, no Git facts are invented, a new fixture
Route can be created without copying A/B, repeated operations are idempotent,
and there is one authoritative source per scope.
