# Project context model

## Entities

- Project is the user-facing product and access boundary.
- Collaboration Root is the durable governance and Route-discovery identity.
- Route is a long-lived development or architecture line.
- Scope is an authorization, knowledge and collaboration-state boundary.
- Root Agent is the project responsibility projection of the current authorized external Session.
- WorkItem is a versioned, acceptable unit under a Route.

A branch, worktree, chat, provider thread or Session is an execution or source
binding. It never replaces Project, Root, Route or WorkItem identity.

## Authority and storage

Project and Root identity originate in the adopted Management Root and manifest.
The Runtime stores adopted identity, revisions and bindings. Repository files
remain authoritative for project-owned instructions and source facts. Runtime
observations carry evidence class and expiry.

Local sessions obtain project_id from AGENTS and the manifest. Web sessions use
list_projects and load_project. Both paths produce the same ProjectContextPack.

## Context completeness

current means every required instruction and source reference is read at the
reported revision. partial lists missing sources. stale identifies a newer
known revision or expired observation. Claims remain bounded by that state.

## Organization and duties

Root/Route describe project/development-line responsibility. Task Agent is the
proposed collective term for explicit task responsibility. Engineer, Reviewer,
Specialist and Finalizer are duties. AgentSlot, Scope, WorkItem and replaceable
Session retain their own identities and cardinalities. Organization metadata
and combined duties remain descriptive; actual Grant/Policy/Profile checks and
candidate-specific reviewer independence apply. Finalizer decisions require
exact candidate/source/evidence/Review and effect/readback prerequisites.
The repository contract is `docs/runtime/AGENT-ORGANIZATION-MODEL.md`.
