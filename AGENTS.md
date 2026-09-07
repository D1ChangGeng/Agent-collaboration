<!-- ACHP:BEGIN -->
## ACHP — Agent Collaboration & Handoff Protocol

This repository uses ACHP for harness-agnostic multi-session / multi-agent collaboration.

**Runtime rule:** normal collaboration is governed by this `AGENTS.md` block and `.agents/`. Do not load or depend on the `agent-collaboration-setup` Skill unless the user explicitly asks to install, repair, upgrade, validate, or remove the collaboration setup itself.

### Session startup

Before material project work:

1. Inspect Git status, branch, and HEAD. Preserve uncommitted work.
2. Read `.agents/coordination/PROJECT.md`.
3. Determine your current role and the active task/handoff.
4. Determine collaboration topology only as far as needed: single-session, multi-session same-host, multi-host, or unknown.
5. For cross-session communication, verify only the capability required by that topology. Never infer capability from a Harness/product name.
6. Treat `unknown` capability as unavailable.
7. Read the smallest relevant durable knowledge under `.agents/knowledge/`.
8. If an incoming task/handoff names a repository commit, confirm your clone has that exact baseline before implementation/review.

### Roles

Default runtime roles are:

- **Coordinator** — product intent, architecture, priorities, task contracts, acceptance criteria, phase progression.
- **Executor** — implementation, tests, technical validation, repository facts, risks, implementation report.
- **Reviewer** — independent verification, acceptance evidence, regression/risk review.

Read role detail only when needed from `.agents/coordination/roles/`.

### Relay policy

Manual user forwarding is a first-class supported transport.

For a message to another session:

- Single session: no relay is needed.
- Same-host multi-session: use automatic relay only if same-host **send** capability is positively verified and the destination is addressable.
- Multi-host: use automatic relay only if cross-host **send** capability is positively verified and the destination is addressable.
- Unknown/unavailable capability: produce one complete copy-ready Relay Envelope for the user to forward.
- Read/discovery capability does not imply send capability.
- Same-host send capability does not imply cross-host send capability.
- Relay capability may be directional; mixed automatic/manual directions are valid.

See `.agents/protocol/CAPABILITIES.md` and `.agents/protocol/RELAY.md` when the current task involves relay decisions.

### Repository synchronization

Session messaging and repository synchronization are independent.

For any handoff involving repository changes, explicitly state:

- branch;
- base/head commit;
- working-tree state;
- whether changes were committed;
- whether Push completed;
- receiver action: none / fetch / pull-required / manual-resolution-required.

Never assume another clone automatically pulled after a message was delivered.

See `.agents/protocol/GIT-SYNC.md` when repository state changes cross session/host boundaries.

### Durable knowledge

`.agents/knowledge/` is the shared project knowledge plane.

Persist a finding only when it plausibly changes a future action/decision and is meaningfully more expensive to rediscover than maintain. Prefer current code/config/tests as factual authority when they are sufficient. Keep evidence and uncertainty visible; correct stale authoritative knowledge instead of accumulating contradictory copies.

See `.agents/protocol/KNOWLEDGE.md` and `.agents/knowledge/README.md` when durable knowledge maintenance is relevant.

### AGENTS.md admission and natural evolution

`AGENTS.md` is the always-on foundation: keep only stable identity and role
boundaries, collaboration topology, high-level behavior invariants,
cross-session continuity rules, and recurring high-cost corrections that every
related session must know before work begins.

Promote a new rule here only when real work shows that it is stable across
future sessions or routes, startup-critical, and not reliably supplied by
retrieved project knowledge. Concrete project state, implementation details,
design rationale, task progress, engineer reports, and temporary evidence stay
in their authoritative knowledge, state, or source records.

The `self-evolution` system owns knowledge discovery, capture, retrieval,
correction, verification, and maintenance. This file may briefly explain a
startup-critical boundary, but it must not become a work log or a second
knowledge lifecycle. Keep one authoritative source for each scope.

### Handoff completion

When another Agent/session will continue, use the templates under `.agents/coordination/templates/` and create a durable handoff under `.agents/coordination/handoffs/` when appropriate.

A handoff must answer:

1. objective;
2. actual result;
3. verification;
4. unresolved items/risks;
5. exact repository state;
6. Push status;
7. receiver sync action;
8. durable knowledge/decision changes;
9. required next action;
10. whether a reply is required.

### Lazy-loading routes

Do not load all collaboration files by default. Read only what the current work needs:

- Capabilities: `.agents/protocol/CAPABILITIES.md`
- Relay: `.agents/protocol/RELAY.md`
- Git sync: `.agents/protocol/GIT-SYNC.md`
- Knowledge: `.agents/protocol/KNOWLEDGE.md`
- Project profile: `.agents/coordination/PROJECT.md`
- Roles: `.agents/coordination/roles/`
- Tasks: `.agents/coordination/tasks/`
- Handoffs: `.agents/coordination/handoffs/`
- Templates: `.agents/coordination/templates/`
- Durable knowledge: `.agents/knowledge/`
<!-- ACHP:END -->
