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

A branch, worktree, machine, directory, provider thread or native Session is a
source, file or execution binding. Replacing one preserves the durable Project
and work identities.

## Authority and storage

Project and Root identity originate in the adopted Management Root and manifest.
Owner registration stores these identities, Routes and the current management
machine, directory and document paths. The directory can reside in Git or another
authorized location. Project-owned files supply instructions and knowledge;
Runtime records supply collaboration state, revisions, bindings and events.

load_project reads current instructions and knowledge indexes through the
machine filesystem. configure_project sets, replaces or clears their saved
location and paths using the current Project revision. A per-call machine_id
and management_path can select another read location.

New single-owner installations select access_mode=owner. Trusted identity,
active service and objects, explicit revocation, deduplication and expected
revisions govern access. A shared deployment also applies configured Grants,
Policy and Profile. An existing configuration with no access mode retains
shared behavior until explicit migration.

## Context completeness and source selection

Local Sessions obtain project_id from AGENTS and the manifest. Web Sessions
discover it through list_projects and load_project. The owner ProjectContextPack
reports Root, Routes, current instructions, knowledge indexes and active work,
with management_root.machine_id/path and each observed document's provenance.

current means the requested management files were read within the reported
budget. partial lists missing locations or documents and provides read_file
follow-ups for larger content. A changed file calls for a new observation
before an action that depends on it. Project revisions track configuration and
collaboration changes; document hashes identify the file contents actually read.

Owner WorkItem.source_baseline may be omitted or null and selected, changed or
cleared by the Agent through eligible intent revisions. Historical Source records
retain their captured identities for explicit source_id/revision queries. The
Agent supplies source observations for the candidate being reviewed. Shared
context and version checks retain their original contract and reference Profile.

The product contract is docs/runtime/OWNER-RUNTIME.md in the ACS release or
source checkout; organization vocabulary is in
docs/runtime/AGENT-ORGANIZATION-MODEL.md.
