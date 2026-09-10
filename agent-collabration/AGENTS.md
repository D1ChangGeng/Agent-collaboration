<!-- ACHP-WORKSPACE:BEGIN -->
## ACHP Project Collaboration Root

This directory is a Project Collaboration Root: a durable Management Root for
project identity, routes, coordination, and source-state evidence. The primary
layout places this Management Root inside the Source Checkout Root. Product
code, management documents, knowledge, and Route directories are tracked in the
same Git repository. Standalone management workspaces remain a compatibility
deployment.

### Startup

1. Read `.agents/coordination/PROJECT.md` and
   `.agents/coordination/ROOT-BASELINE.md`.
2. Read `.agents/coordination/routes.yaml` to discover Route Nodes.
3. Read only the matching route's own `AGENTS.md` and `.agents/knowledge/` when
   working on that route. Root knowledge is not a replacement for route-owned
   knowledge.
4. Read `.agents/protocol/SOURCE-STATE.md` before making claims about code,
   branches, endpoints, or execution status.
5. Inspect the containing source checkout's Git state when the task involves
   tracked management or source files. Bind branch, commit, and working-tree
   claims to that checkout; use `unknown`, `unverified`, or `not-measured` for
   facts that have not been established.

### Scope and ownership

- Root owns stable project identity, route registry, cross-route coordination,
  and the Root↔Route migration contract.
- A Route Node owns its identity metadata, durable goals, decisions, knowledge,
  and verified source evidence. The Root registry owns lifecycle status and
  display name; live Session progress remains in the current Harness context.
- An Execution Endpoint is replaceable runtime capacity, not a permanent Route
  identity.
- Management, Source Repository state, and Execution Endpoint responsibilities
  remain logically separate when their files share one Git repository.
- Local and remote hosts use distinct clones with the same repository-relative
  Management Root and Route layout. Absolute paths may differ; synchronization
  requires explicit Git operations.
- In the nested layout, the Source Checkout Root's `.gitignore` owns scoped
  rules for transient files and secrets; the Management Root has no child
  `.gitignore`.
- Do not assume this file is automatically inherited by a child Route. Harness
  discovery is runtime-specific; use the explicit Root contract path.
- `self-evolution` owns durable-knowledge lifecycle; ACHP owns collaboration
  topology and state boundaries.
- Harness/session context and capability observations are local to the running
  environment. They are not required Project Collaboration Workspace state.

### AGENTS.md admission and natural evolution

This Root file contains only always-on collaboration invariants: stable identity
and role boundaries, Root/Route/Endpoint/Source-State separation, high-level
topology and behavior rules, cross-session continuity, and recurring high-cost
corrections that every related session must know before work begins.

Promote a new rule here only when real work shows that it is stable across
future sessions or Routes, startup-critical, and not reliably supplied by
retrieved Root or Route knowledge. Current project state, implementation
details, design rationale, task progress, engineer reports, and temporary
evidence remain in their authoritative Route, state, knowledge, or source
records.

`self-evolution` owns knowledge discovery, capture, retrieval, correction,
verification, and maintenance. The Root file does not duplicate that lifecycle
and must not become a work log or a second source of truth.

See `.agents/coordination/ROOT-BASELINE.md`, `.agents/protocol/RELAY.md`,
`.agents/protocol/GIT-SYNC.md`, and `.agents/protocol/SOURCE-STATE.md` for the
deeper contracts.
<!-- ACHP-WORKSPACE:END -->

## Source repository and Git working directory

- The formal local source repository is `D:\Chatgpt\Agent-collaboration`.
- This management workspace is `D:\Chatgpt\Agent-collaboration\agent-collabration`.
- The management workspace is tracked content inside the source repository; it
  is not a separate Git checkout and does not own a competing repository state.
- Run repository-level `status`, `branch`, `fetch`, `pull`, `merge`, `commit`,
  `push`, tag, and release commands with the working directory set to
  `D:\Chatgpt\Agent-collaboration`.
- When operating on the remote engineering checkout, use
  `/home/changgeng/Agent-collaboration` as its Git working directory. Confirm
  its branch, HEAD, working-tree state, and upstream before synchronization.
- Keep management file paths relative to this workspace when editing them, but
  use the source-repository root for all Git synchronization and publication
  operations.

<!-- ACHP-SOURCE-CHECKOUT:BEGIN -->
## Local source checkout and Git working directory

- Local source checkout relative to this Management Root: `..`.
  Resolve this path from the directory containing this `AGENTS.md`, then use
  the resolved source checkout as the repository working directory.
- Run repository synchronization, `fetch`, `pull`, `status`, `diff`, `add`,
  `commit`, `merge`, and `push` with the working directory set to that local
  source checkout. This also applies when the Agent session starts in the
  Management Root. Change the command working directory or use
  `git -C <resolved-source-checkout> ...` explicitly.
- The Management Root scopes coordination and knowledge files; the containing
  source checkout scopes Git operations for both product and management files.
  Verify branch, HEAD, working-tree state, and upstream before synchronization.
<!-- ACHP-SOURCE-CHECKOUT:END -->

## Runtime contract route

Runtime implementation and acceptance follow `../docs/runtime/UPGRADE-CONTRACT.md`
and the registered `collaboration-runtime` Route. Keep Runtime Domain state and
Gate evidence separate from the setup manifest, Route registry and knowledge
lifecycle. External Agents own reasoning, delegation and acceptance decisions;
the Runtime applies authenticated commands and deterministic recovery.
