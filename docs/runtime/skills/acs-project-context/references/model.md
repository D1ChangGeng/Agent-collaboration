# Project context model

## Entities

- Project is the user-facing product and access boundary.
- Collaboration Root is the durable governance and Route-discovery identity.
- Route is a long-lived development or architecture line.
- Scope is an authorization, knowledge and collaboration-state boundary.
- Root Agent is the current external Session acting with management authority.
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
