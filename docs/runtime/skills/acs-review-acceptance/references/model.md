# Review and acceptance model

Review request identifies type, exact candidate, source baseline, workspace
view when applicable, criteria, required Evidence and reviewer assignment.
Review result records decision, findings, evidence references, source readback
and unresolved items.

Architecture Review evaluates boundaries, invariants and change impact.
Engineering Review evaluates correctness, regression and operability. Evidence
Review evaluates claim support and its measured scope. Finalization Review
evaluates the integrated candidate and acceptance prerequisites.

The adopted acceptance profile verifies candidate-specific reviewer identity
and independence. Root and Route describe responsibility extent; Engineer,
Reviewer, Specialist and Finalizer describe duties. Team metadata guides
assignment, while the actual candidate and reviewer records establish
independence.

Artifact hashes and deterministic storage preserve candidate identity.
AcceptedStateRevision is immutable and records parent revision, accepted_by,
candidate, source, Evidence, Review, effects, readback and applicable Policy.

Owner admission uses continuous trusted identity, active objects, explicit
revocation, deduplication and revisions. Shared mode adds its configured
Grant and Policy checks. Completed execution and Review facts preserve their
original provenance after a prior Grant's natural expiry. A current claim about
source or readiness requires current evidence.
