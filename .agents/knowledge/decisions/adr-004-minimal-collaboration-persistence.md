---
kind: decision
id: adr-004-minimal-collaboration-persistence
status: accepted
date: 2026-09-06
scope:
  - "scripts/workspace_setup.py"
  - "scripts/project_setup.py"
  - "assets/scaffold/**"
  - "SKILL.md"
  - "README.md"
  - "README.zh-CN.md"
  - "references/**"
supersedes: null
---

# Context

A Project Collaboration Workspace needs enough durable information for a new
session to identify the Root and its Routes, but Session execution progress,
capability observations, source facts, and reviewed knowledge already have more
appropriate authorities.

# Decision

Workspace schema 0.3 keeps Route lifecycle status, display name, path, and ID in
the Root registry. Route metadata keeps only Route/Root identity, the canonical
path, and the explicit Root contract pointer. The Workspace manifest keeps the
Root identity, registry location, setup boundary, and stable Workspace kind.

Installer ownership inventories and hashes are optional setup-integrity
metadata. Harness/session context owns live Session execution and capability
observations; Git or explicit Source State Evidence owns source identity;
self-evolution owns durable knowledge. The setup Skill configures these
boundaries and does not own Session execution recovery.

Route creation does not pre-create an empty Source State record. A Route may
add `.agents/state/source-state.yaml` only when independently verified source
facts have durable cross-Session value. The record excludes live Harness,
Session, process, and Endpoint status.

# Consequences

Lifecycle has one authority, pointers are minimized, and shared writes are
limited to stable control-plane metadata. Machine-local capability observations
remain in the Harness/session context. Schema 0.2 input remains readable, while
explicit upgrade removes recognized deprecated fields and preserves strict-JSON
extension fields.

# Evidence

The decision is enforced by the Workspace/Route validators and regression tests
for schema compatibility, registry-only lifecycle writes, Route metadata
canonicalization, Windows newline idempotency, optional integrity ledgers,
extension preservation, and fail-closed path/input handling.

# Reconsider When

Reconsider only when repeated real workflows demonstrate a specific durable
fact that cannot be recovered from Harness context, Workspace files, Git/Source
State, or durable knowledge, and the maintenance cost of a new authority is
lower than the measured rediscovery cost.
