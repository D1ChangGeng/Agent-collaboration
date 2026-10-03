# Review and acceptance model

Review request identifies type, candidate, exact source baseline, criteria,
required Evidence and reviewer constraints. Review result records decision,
findings, evidence handles, source readback and unresolved items.

Architecture Review evaluates boundaries, invariants and change impact.
Engineering Review evaluates implementation correctness, regression and
operability. Evidence Review evaluates claim support and validity. Finalization
Review evaluates the integrated candidate and acceptance prerequisites.

AcceptedStateRevision is immutable and records parent revision, accepted_by,
Policy version, candidate, source, Evidence, Review, effect and readback handles.

## Organization and duties

Root/Route describe project/development-line responsibility. Task Agent is the
proposed collective term for explicit task responsibility. Engineer, Reviewer,
Specialist and Finalizer are duties. AgentSlot, Scope, WorkItem and replaceable
Session retain their own identities and cardinalities. Organization metadata
and combined duties remain descriptive; actual Grant/Policy/Profile checks and
candidate-specific reviewer independence apply. Finalizer decisions require
exact candidate/source/evidence/Review and effect/readback prerequisites.
The repository contract is `docs/runtime/AGENT-ORGANIZATION-MODEL.md`.
