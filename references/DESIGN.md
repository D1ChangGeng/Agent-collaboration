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
- uninstall;
- route harness-specific persistent instruction entry points to the same runtime contract.

### Runtime collaboration plane

Installed into each target repository.

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
