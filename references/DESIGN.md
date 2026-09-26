# Design: Setup-only Skill, Runtime-native Collaboration

## Core separation

There are two systems with deliberately different lifecycles.

### Setup plane

Provided by this Skill.

Responsibilities:
- install;
- adopt;
- upgrade;
- repair;
- validate;
- repository uninstall where the ownership boundary is known;
- route harness-specific persistent instruction entry points to the same runtime contract.

For the current Workspace schema 0.3, the corresponding command family is
explicit and exact-path based. `workspace bootstrap`, `adopt`, `upgrade`,
`repair`, and `validate` are implemented; `workspace uninstall` is currently
guarded and refuses to change files until a reviewed ownership plan is
available. Schema 0.2 input remains readable, while new writers emit the
minimal stable shape. This deliberate refusal is a safety boundary, not a
second uninstall semantics.

### Workspace directory model

The preferred v0.4.0 model places the management root in the same project Git
repository as product code:

```text
Project Git Repository / Source Checkout Root
├── Product code
├── ...
└── Nested Management Root
    ├── AGENTS.md
    ├── .agents/
    └── Route directories
```

Management documents, knowledge, and Routes share project Git commits with
product code. Separate local and remote clones keep the same relative layout
and synchronize through explicit Git operations. The manifest records only the
directory mode `nested-repository`; Git carries the relative layout.

The CLI retains the exact nested root. Its only parent write is scoped runtime
exclusions in repository-root `.gitignore`, using a separate
`# ACHP-NESTED:<relative path>:BEGIN` / `# ACHP-NESTED:<relative path>:END` block.
Existing parent blocks and rules are preserved. The nested root has no child
`.gitignore`, and parent repository scaffolding is not a prerequisite.
Standalone Workspaces remain supported for compatibility. Legacy manifests
without the mode remain unchanged during `adopt`/`repair`; explicit Workspace
upgrade inside Git migrates known setup-only child ignores. Custom child rules
require reviewed manual consolidation before writes proceed.

### Runtime collaboration plane

Installed into each target repository, or into the Root/Route surfaces of a
management Workspace.

Responsibilities:
- roles;
- collaboration topology;
- capability-based relay;
- user manual relay;
- handoffs;
- Git synchronization;
- durable project knowledge;
- task progression.

The runtime MUST remain functional if this Skill is deleted from the machine after setup.

## Four runtime planes

### Execution Plane
Agents/sessions perform work.

### Coordination Plane
Roles, tasks, handoffs, message envelopes.

### Repository State Plane
Git branch, commits, Push/Pull, exact baselines.

### Knowledge Plane
Durable shared project knowledge under `.agents/knowledge/`.

In a compatible standalone non-Git Workspace, the Repository State Plane is represented as explicit
Source State Evidence and may remain `unknown`, `unverified`, or
`not-measured`. A Workspace Root is a management/control surface, not an
implicit execution checkout.

## Schema 0.3 Route operation boundary

The current Route CLI implements `create`, `adopt`, `list`, `validate`,
`upgrade`, `set-state`, and `rename`. Route metadata stores identity and the
explicit Root contract pointer. Lifecycle and display name are authoritative in
the Root registry; `set-state` and `rename` write that registry only. `route
upgrade` is the explicit metadata migration boundary and preserves unrecognized
extension fields. Verified Source Repository facts may use an optional
Route-owned `.agents/state/source-state.yaml` record when they need durable
cross-Session value; new Routes do not receive an empty record. The Root
registry does not store these fields. Harness, Session, and live Endpoint status
remain current-context observations, not Source State.

Path-moving rename, split/merge, Endpoint replacement, restore, rollback, and
other ownership-changing lifecycle actions are documented future migration
contracts. They require an explicit plan, evidence, dry-run, review, and
reversible recovery before implementation; they are not implied by the current
metadata commands.

## Transport abstraction

The protocol standardizes a Relay Envelope, not a specific API.

Transport selection is a runtime policy:

```text
required collaboration?
  no -> none
  yes
    |
    +-- same host?
    |     +-- same-host send verified + addressable target -> automatic
    |     +-- otherwise -> user manual
    |
    +-- different host?
          +-- cross-host send verified + addressable target -> automatic
          +-- otherwise -> user manual
```

If topology is unknown, manual relay is non-blocking and safe.

## Why manual relay is a first-class transport

It is:
- ubiquitous;
- inspectable;
- cross-machine;
- vendor-independent;
- not dependent on hidden APIs.

This gives ACHP a portable baseline.

## Runtime capability belongs to current session context

A capability observation is scoped to the harness, version, host, session,
permission set, and installed tool set that produced it. Keep those observations
with the current Harness/session context. Installer metadata records setup
integrity; Git or Route Source State records source identity; self-evolution
manages durable knowledge. The setup Skill configures these boundaries and does
not own Session execution recovery.

## Why `AGENTS.md` is canonical

Codex and OpenCode discover `AGENTS.md` directly.

Claude Code does not use `AGENTS.md` as its native project memory entry point, but officially supports importing it from `CLAUDE.md`.

Therefore ACHP uses:
- one canonical `AGENTS.md`;
- a minimal Claude compatibility import;
- no duplicated runtime protocol bodies.

### AGENTS admission and natural evolution

`AGENTS.md` is a small always-on foundation, not a project journal. It should
contain stable identity and role boundaries, collaboration topology, durable
ownership and evidence boundaries, cross-session continuity rules, and
high-cost corrections that every related session needs at startup.

An observed rule is eligible for promotion only when it is stable across future
sessions or Routes, startup-critical, and not reliably recoverable through
retrieved knowledge. Current implementation state, design rationale, task
progress, engineer reports, and temporary evidence remain in their authoritative
Route, state, knowledge, or source records. `self-evolution` owns discovery,
capture, retrieval, correction, verification, and maintenance; ACHP only keeps
the boundary that lets those layers work together without a second lifecycle or
source of truth.

## Knowledge philosophy

The knowledge plane should remain sparse.

Persist only information that:
- changes a likely future action;
- is materially expensive to rediscover;
- is not already more authoritative in source/config/tests;
- has a clear scope and evidence boundary.

This is compatible with self-evolution-style project knowledge management without making ACHP depend on a specific knowledge Skill.
