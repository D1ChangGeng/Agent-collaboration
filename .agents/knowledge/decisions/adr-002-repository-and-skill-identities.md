---
kind: decision
id: adr-002-repository-and-skill-identities
status: accepted
date: 2026-09-05
scope:
  - "SKILL.md"
  - "scripts/validate_skill.py"
  - "README.md"
  - "README.zh-CN.md"
supersedes: null
---

# Context

The source repository is being restored under the product name
`Agent-collaboration`, while the already-published installable Skill has the
canonical slug `agent-collaboration-setup`. A validator that compares the
frontmatter name to the source directory would reject this valid arrangement.

# Decision

Keep the two identities separate:

- Repository: `Agent-collaboration`.
- Installable Skill slug and discovery directory: `agent-collaboration-setup`.

Validation checks the canonical Skill slug and portable metadata, not the source
repository directory name.

# Alternatives considered

- Rename the repository directory to match the Skill slug: rejected because it
  confuses source-repository identity with installation identity.
- Change the Skill slug to `Agent-collaboration`: rejected because it breaks the
  existing discovery/install contract and portable lowercase slug.

# Consequences

The validator can be run from the repository root without imposing a naming
constraint that is not part of the Agent Skills contract. Documentation and
release tooling must continue to distinguish the repository from the Skill.

# Evidence

The original v0.1.0 archive uses `agent-collaboration-setup` in `SKILL.md` and
the setup manifest. The deterministic validator was corrected to assert that
canonical slug rather than `Path.name`; the full unit suite passes after the
change.

# Reconsider when

Reconsider only if the publication/discovery contract or the repository's
identity is intentionally changed in a versioned release.
