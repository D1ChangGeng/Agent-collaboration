# Review and acceptance model

Review request identifies type, exact candidate, criteria, required recorded
Evidence and reviewer assignment, together with a selected WorkItem baseline
when present. Owner WorkItem.source_baseline may be omitted or null. An eligible
intent revision can select, change or clear that version while existing Evidence
keeps its recorded source facts. Review result records decision, findings,
Evidence references, source readback and unresolved items.

For owner Review and acceptance, the Agent observes the candidate through Git,
native tools or machine files and actively reports source_readback.commit/tree.
The recorded Evidence and execution receipts must agree with that candidate and
observed version. Relevant local edits and workspace state belong to the
candidate evidence supporting the claim.

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
candidate, selected source baseline when present, Evidence, Review, effects,
readback and applicable Policy.

Owner admission uses continuous trusted identity, active objects, explicit
revocation, deduplication and revisions. Shared mode retains its configured
Grant, Policy, SourceBinding and clean-checkout readback checks. Completed
execution and Review facts preserve their original provenance after a prior
Grant's natural expiry. A current claim about source or readiness requires
current evidence. Historical reference results retain their measured scope.
