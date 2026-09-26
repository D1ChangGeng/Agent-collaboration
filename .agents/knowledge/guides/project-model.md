---
kind: guide
status: active
scope:
  - "SKILL.md"
  - "README.md"
  - "README.zh-CN.md"
  - "references/**"
  - "assets/scaffold/CLAUDE_BLOCK.md"
use_when:
  - "deciding whether a change belongs to the setup Skill or the runtime protocol"
  - "onboarding a new agent to Agent-collaboration"
  - "reviewing product identity, scope, or release claims"
review_when:
  - "the Skill slug, repository identity, or setup/runtime boundary changes"
---

# Purpose

Agent-collaboration is the source repository for a Harness-agnostic Agent
Collaboration & Handoff Protocol (ACHP) and its setup-only Skill. The repository
name is `Agent-collaboration`; the installable Skill identity remains
`agent-collaboration-setup`.

# Product boundary

The Skill performs only `bootstrap`, `adopt`, `upgrade`, `repair`, `validate`,
and `uninstall`. It installs or maintains repository-native collaboration files
and then exits the normal runtime path. Coordinator, Executor, Reviewer, task
handoff, relay, Git synchronization, and knowledge maintenance are governed by
`AGENTS.md` and `.agents/`.

This separation permits the project to change Harnesses without redesigning the
collaboration protocol. Harness-specific integrations are compatibility edges,
not the protocol core.

# Evidence and authority

The portable Skill contract is in `SKILL.md`; user-facing scope and examples are
in the two README files; architecture and compatibility details are in
`references/`; installed runtime semantics are in `.agents/protocol/` and the
managed `AGENTS.md` block. Tests and scripts are the authority for deterministic
validation behavior.

# Constraints

- Do not turn the setup Skill into a runtime agent or hidden dependency.
- Do not infer runtime capability from a Harness or product name.
- Do not copy a second authoritative protocol into `CLAUDE.md`; it is only a thin
  `@AGENTS.md` router.
- Treat unknown capability as unavailable until the exact capability is verified.

# Verification

Run `python scripts/validate_skill.py`, the Python unit suite, and
`python scripts/project_setup.py validate --root .` after changes to the setup
contract. Re-read the referenced source files when material claims change.
