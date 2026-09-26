---
kind: runbook
status: active
scope:
  - "scripts/**"
  - "tests/**"
  - ".github/**"
  - "VERSION"
  - "CHANGELOG.md"
  - "CONTRIBUTING.md"
  - "SECURITY.md"
use_when:
  - "implementing a change in this repository"
  - "preparing a v0.1.x or later release"
  - "reviewing whether a change is in the current initialization scope"
review_when:
  - "test commands, package boundaries, or release packaging change"
---

# Standard development loop

1. Classify the change as Setup Skill, Runtime Protocol, Harness Adapter, or
   Documentation.
2. Read the smallest matching Guide/Decision and the authoritative source.
3. Make the smallest scoped change while preserving project-owned state.
4. Run the deterministic validator and unit tests.
5. Run project setup validation and `git diff --check`.
6. Capture only durable future-action knowledge with self-evolution; do not copy
   routine implementation details into the Knowledge Plane.
7. Update `VERSION`/`CHANGELOG.md` only when the change is release-worthy.
8. Review the staged diff, commit, push when authorized, and report receiver pull
   requirements.

# v0.1.0 initialization acceptance

The recovery acceptance set is:

```text
python scripts/validate_skill.py
python -m unittest discover -s tests -v
python scripts/project_setup.py validate --root .
node <installed-self-evolution>/references/bin/kb.mjs index --project-root . --format text
node <installed-self-evolution>/references/bin/kb.mjs check --project-root . --format text
git diff --check
```

The release Skill artifact must not contain `.git/`, machine-local runtime state,
secrets, temporary extraction files, or this repository's development-only root
`.agents/` state. The source repository and installable Skill artifact are
different publication boundaries even though they share the Skill source.

# Scope guard

Do not use v0.1.0 initialization to add a broker, daemon, UI, complex session
orchestration, or a large new Harness adapter. Record worthwhile future ideas as
reviewed observations or roadmap decisions instead.
