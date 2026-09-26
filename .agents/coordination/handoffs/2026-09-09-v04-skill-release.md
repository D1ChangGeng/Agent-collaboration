---
id: HANDOFF-2026-09-09-V04-SKILL-RELEASE
task: V04-SKILL-USER-JOURNEY-RELEASE
from_role: Coordinator/Executor/Reviewer
to_role: next Skill-maintenance session
created_at: 2026-09-09
status: completed
---

# Objective

Publish the reviewed v0.4.0 `agent-collaboration-setup` Skill with the
user-journey safety hardening, minimal Workspace schema 0.3 state boundary,
and verified portable release artifacts.

# Actual result

v0.4.0 was committed, pushed to `origin/main`, tagged with an annotated
`v0.4.0` tag, and published as a non-draft, non-prerelease GitHub Release.
The release keeps the Skill setup-only: normal collaboration remains governed
by `AGENTS.md` and `.agents/`, while Harness Session, Endpoint, relay, and
runtime recovery observations remain outside Skill-owned durable state.

The release adds Agent-facing operating/capability/scenario guidance, exact
path and reparse protections, explicit Route candidate selection, conservative
create/adopt/upgrade behavior, ownership and drift checks, atomic writes, and
target-scoped Route operations. A missing unrelated sibling remains visible to
Workspace-wide validation without blocking a valid selected Route operation.

# Files / artifacts changed

Release commit `d40435513d744e8e0f3fbb214bd78bf8c6e2c5ea` contains the v0.4.0
implementation, references, scaffold updates, and regression tests. The
following release assets were generated from the exact `v0.4.0` tag payload:

```text
dist/agent-collaboration-setup-v0.4.0.zip
  bytes: 140776
  entries: 99 (69 files, 30 directories)
  sha256: 19dcd572ba2104d0dc7c867af58ddfe6d04f56060d437824e718383d6c80e242

dist/agent-collaboration-setup-v0.4.0.tar.gz
  bytes: 108385
  entries: 99 (69 files, 30 directories)
  sha256: 65e2ff9d81dc090c5750558db3fe656b265d77bd5a0cc56b08b03fbf3682342f
```

The archives contain the explicit Skill payload under the
`agent-collaboration-setup/` root. Repository `.agents/` state,
`RFC_TEMP_SOURCE/`, `dist/`, caches, and runtime/session data are outside the
artifact boundary. The installer-generated ownership marker is target-local
and is not distributed in the archives.

# Verification

- `python -B -m unittest discover -s tests -q`: 93 tests passed; 4 Windows
  symlink tests skipped because the current process lacks symlink-creation
  privilege.
- `python -B scripts/validate_skill.py`: PASS.
- Skill Creator quick validation: PASS.
- Python compilation, repository setup validation, self-evolution `kb index`,
  self-evolution `kb check`, and `git diff --check`: PASS.
- Both local archives were extracted in isolation and passed Skill validation,
  compilation, and the full test suite.
- Both assets were downloaded from the GitHub Release and matched the local
  byte counts and SHA-256 digests; remote extraction validation also passed.
- Annotated tag object:
  `d31ab8764f646b5252e6e185953d5ee968d6924c`.
- Annotated tag target:
  `d40435513d744e8e0f3fbb214bd78bf8c6e2c5ea`.

# Unresolved items and risks

- Session enumeration/targeting, Session attach/replacement, Endpoint
  replacement, machine migration, SSH adapters, direct same-host or
  cross-host relay, collaboration configuration migration, natural-language
  CLI parsing, and runtime checkpoint/recovery remain outside the current
  Skill capability boundary.
- Workspace-wide validation intentionally remains stricter than a selected
  Route operation; a damaged or missing sibling must still be repaired or
  reviewed before the Root can be considered globally valid.
- The four skipped symlink tests require a Windows process with symlink
  creation privilege for additional platform coverage.
- `RFC_TEMP_SOURCE/` is preserved as external research input, is not staged,
  and is not an authoritative project-fact source.

# Repository Sync

- Branch: `codex/v04-user-journey`
- Base commit: `2b992a49b1349de0902443de215ee3bf2b975679`
- Release commit: `d40435513d744e8e0f3fbb214bd78bf8c6e2c5ea`
- Post-release handoff commit: this commit, recorded in Git history
- Working tree: tracked files clean; untracked `RFC_TEMP_SOURCE/` intentionally
  preserved outside the release
- Push: release commit and this handoff commit pushed to `origin/main`
- Tag: annotated `v0.4.0`, fixed to the release commit above
- Release: GitHub `Agent-collaboration v0.4.0`, non-draft and non-prerelease
  (`https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v0.4.0`)
- Receiver sync: `fetch` (`origin/main` and `v0.4.0`; other clones must verify
  the exact handoff commit before continuing)

# Knowledge / decision updates

The accepted minimal-persistence decision remains authoritative:
`.agents/knowledge/decisions/adr-004-minimal-collaboration-persistence.md`.
The project profile now records v0.4.0 as published. No Route-owned or A/B
Route product state was changed in this Skill release.

# Required next action

Other clones or sessions should fetch `origin/main` and the annotated
`v0.4.0` tag, then run the documented validation commands. Any future A Route,
B Route, or `D:\\Chatgpt\\Agent` Workspace collaboration-system change must use
its own dedicated task/thread and evidence; it is not implied by this Skill
release.

# Reply required

Yes. Report the release commit, post-release handoff commit, tag, GitHub
Release, artifact digests, and receiver fetch action when handing off this
state.
