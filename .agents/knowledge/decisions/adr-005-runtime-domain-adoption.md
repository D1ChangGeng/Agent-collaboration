---
kind: decision
id: adr-005-runtime-domain-adoption
status: accepted
date: 2026-09-11
scope:
  - "docs/runtime/**"
  - "tools/runtime/**"
  - "agent-collabration/**"
supersedes: null
---

# Runtime authority and setup compatibility

The user authorized the Harness-agnostic Collaboration Runtime / Control Plane
upgrade. The adopted [Runtime contract](../../../docs/runtime/UPGRADE-CONTRACT.md)
records the source instruction digest, RFC precedence and required P1/P2 Gates.

The setup Skill and Workspace schema keep their existing identity and ownership.
ADR-001 and ADR-004 continue to govern setup. Runtime features have their own
package/schema adoption and PostgreSQL Domain authority. Node SQLite journals,
Provider history and Harness sessions are scoped observations or execution
records, with no competing write authority over Domain state.

External Agents own intelligent decisions, including work decomposition,
delegation, review and acceptance requests. Runtime executes authenticated
deterministic commands, preserving grants and lineage during recovery. Runtime
Human Bridge is a bounded recovery incident after automatic-path exhaustion.

WorkItem acceptance is candidate, acceptance_ready, accepted; execution and
publication/effect status remain separate. This upgrade requires independent
review and integrated-baseline evidence. Codex-to-Codex dual-machine acceptance
precedes Codex-to-OpenCode, and a P2 product-owner decision closes the Gate review.

This decision changes future implementation and validation choices. It does not
assert that mechanisms or end-to-end scenarios have passed. Reconsider only if
real evidence contradicts the adopted boundary or the user changes product
direction, risk authorization or the required acceptance Profile.
