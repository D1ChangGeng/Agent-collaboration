# Project context model

## Entities

Project is the product and data boundary. Collaboration Root owns durable
project identity and Route discovery. Route is a long-lived development or
architecture line. Scope groups collaboration state, knowledge and object
ownership. AgentSlot identifies an addressable responsibility. WorkItem is a
versioned deliverable under that context.

Root Agent is the current external Session's project responsibility projection.
Root and Route describe responsibility extent; Engineer, Reviewer, Specialist
and Finalizer describe duties. Team roles and organization metadata guide
delegation. Candidate-specific reviewer independence remains a separate check.

A branch, worktree, machine, provider thread or native Session is a source or
execution binding. Replacing one preserves the durable Project and work
identities.

## Authority and storage

Project and Root identity originate in the adopted Management Root and manifest.
The Runtime stores adopted identities, revisions, business bindings and events.
Repository files remain authoritative for project-owned instructions and
source. Current workspace observations have a view revision; a fixed source
snapshot keeps its exact baseline and bytes.

New single-owner installations select `access_mode=owner`. Trusted identity,
active service and objects, explicit revocation, deduplication and expected
revisions govern access. A shared deployment also applies configured Grants,
Policy and Profile. An existing configuration with no access mode retains
shared behavior until explicit migration.

## Context completeness

Local Sessions obtain project_id from AGENTS and the manifest. Web Sessions
discover it through list_projects and load_project. ProjectContextPack reports
Root, Routes, instructions, SourceBindings, knowledge and active work.

`current` means required context has been read at the reported revision.
`partial` lists missing sources. `stale` records a newer known source revision
or an observation that needs refresh. Owner registration persists, while
current source and process readiness still require actual readback.

The product contract is `docs/runtime/OWNER-RUNTIME.md` in the ACS release or
source checkout; organization vocabulary is in
`docs/runtime/AGENT-ORGANIZATION-MODEL.md`.
