# Review and acceptance tool map

- list_reviews discovers assignments and completed decisions.
- request_review creates an exact candidate and Evidence-bound assignment;
  owner source_baseline is optional when the WorkItem has no selected version.
- submit_review records the structured decision, findings and supporting facts.
- list_evidence and read_resource inspect exact supporting records.
- Git, native tools and read_file establish the candidate actually inspected;
  historical read_source and read_diff use explicit archive selections.
- accept_work commits AcceptedStateRevision after the applicable prerequisites.
- Eligible revise_work can select, replace or clear an owner work version.

Owner submit_review and accept_work receive the Agent's actively observed
commit/tree through source_readback. They compare that report with recorded
candidate Evidence and execution receipts. Candidate identity, Evidence inventory
and content, reviewer independence, integrated results and protected-effect
readback remain acceptance checks.

Owner invocation checks authenticated identity, active objects, explicit
revocation, stable request identity and expected revisions. Shared deployments
retain their Grant, Policy, SourceBinding and clean-checkout readback checks.
Exact inputs come from the installed access mode's active tool schema.

Completed Artifact and Review records retain their original digests and
provenance. Read their exact identities; refresh evidence when evaluating a
claim about the current source or running system. Historical reference results
retain the scenario and configuration they measured.
