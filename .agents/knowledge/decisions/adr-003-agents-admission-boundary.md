---
kind: decision
id: adr-003-agents-admission-boundary
status: accepted
date: 2026-09-06
scope:
  - "AGENTS.md"
  - "assets/scaffold/AGENTS_BLOCK.md"
  - "assets/scaffold/workspace/AGENTS_BLOCK.md"
  - "assets/scaffold/workspace/ROUTE_AGENTS.md"
  - "SKILL.md"
  - "references/DESIGN.md"
supersedes: null
---

# Context

The long-running A and B Route histories established that a new session needs
stable collaboration identity, topology, ownership, evidence, and continuity
at startup, while concrete project knowledge and changing work state must remain
retrievable rather than being copied into every `AGENTS.md`.

# Decision

`AGENTS.md` is the always-on foundation. A new rule is eligible for promotion
only when real work shows that it is stable across future sessions or Routes,
startup-critical, and not reliably supplied by retrieved knowledge. Concrete
state, implementation detail, design rationale, task progress, reports, and
temporary evidence remain in their authoritative Route, state, knowledge, or
source records. `self-evolution` owns knowledge discovery, capture, retrieval,
correction, verification, and maintenance.

# Consequences

Repository, Workspace, and Route scaffolds now carry the same lightweight
admission boundary. Future upgrades can add a genuinely shared invariant
without turning `AGENTS.md` into a work log or creating a second knowledge
lifecycle. Route-specific knowledge remains Route-owned.

# Evidence

The decision was derived from the complete user-message histories available for
the A and B parent threads. The histories were read page-by-page to their
earliest available records; the stable result was then checked against the
current Skill scaffold, Workspace control plane, and regression tests.

# Reconsider When

Reconsider only if a future collaboration model changes the startup contract,
the durable-knowledge boundary, or the authority of `AGENTS.md` in a versioned
protocol migration.
