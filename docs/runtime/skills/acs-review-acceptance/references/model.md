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
