---
name: acs-review-work
description: Perform or delegate an independent ACS architecture, engineering, evidence, or finalization review against an exact candidate and source baseline. Use for review requests, findings, risk assessment, and approval recommendations.
---

# ACS Review Work

Canonical tools: load_project, request_review, list_evidence, read_source, read_diff, submit_review.

Select review_type from architecture, engineering, evidence or finalization.

1. Load the project with context_view reviewer.
2. Resolve the Review request or create one with candidate, exact source
   baseline, criteria, evidence requirements and reviewer constraints.
3. Verify reviewer independence and current authorization.
4. Read Route and WorkItem intent, accepted state and constraints.
5. Read source state, bounded diff, tests, Evidence and Artifact metadata.
6. Compare claims with direct readback and retain uncertainty.
7. Produce findings with severity, affected resource, evidence, consequence and
   required action.
8. Submit the structured Review with decision, findings, evidence handles,
   source readback and unresolved items.

Architecture review emphasizes boundaries, invariants and change impact.
Engineering review emphasizes implementation correctness, regression and
operability. Evidence review checks claim support and validity. Finalization
review checks the integrated candidate and acceptance prerequisites.
