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

For a schema 0.2 Project Collaboration Workspace, the corresponding command
family is explicit and exact-path based. `workspace bootstrap`, `adopt`,
`upgrade`, `repair`, and `validate` are implemented; `workspace uninstall` is
currently guarded and refuses to change files until a reviewed ownership plan is
available. This deliberate refusal is a safety boundary, not a second uninstall
semantics.

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

In a non-Git Workspace, the Repository State Plane is represented as explicit
Source State Evidence and may remain `unknown`, `unverified`, or
`not-measured`. A Workspace Root is a management/control surface, not an
implicit execution checkout.

## Schema 0.2 Route operation boundary

The current Route CLI implements `create`, `adopt`, `list`, `validate`,
`set-state`, and `rename`. `rename` updates display metadata only; it does not
move a directory or rewrite Route-owned files. Endpoint bindings are pointers
until independently evidenced, not a claim that Endpoint replacement is
available.

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

## Why runtime capability is not durable project knowledge

A capability observation belongs to a specific:
- harness;
- version;
- host;
- session;
- permission set;
- installed tool set.

Committing that as project truth creates false assumptions on another machine.

Therefore runtime observations belong in `.agents/runtime/`, which is ignored by Git.

## Why `AGENTS.md` is canonical

Codex and OpenCode discover `AGENTS.md` directly.

Claude Code does not use `AGENTS.md` as its native project memory entry point, but officially supports importing it from `CLAUDE.md`.

Therefore ACHP uses:
- one canonical `AGENTS.md`;
- a minimal Claude compatibility import;
- no duplicated runtime protocol bodies.

## Knowledge philosophy

The knowledge plane should remain sparse.

Persist only information that:
- changes a likely future action;
- is materially expensive to rediscover;
- is not already more authoritative in source/config/tests;
- has a clear scope and evidence boundary.

This is compatible with self-evolution-style project knowledge management without making ACHP depend on a specific knowledge Skill.
