# Review and acceptance tool map

- list_reviews discovers assignments and completed decisions.
- request_review creates a candidate and source-bound Review assignment.
- submit_review records the structured decision, findings and supporting facts.
- list_evidence and read_resource inspect exact supporting records.
- read_source and read_diff establish the committed or workspace candidate
  actually inspected.
- accept_work commits AcceptedStateRevision after the applicable prerequisites.

Owner invocation checks authenticated identity, active objects, explicit
revocation, stable request identity and expected revisions. The acceptance
profile still checks exact candidate, source, reviewer independence, evidence,
integrated results and protected-effect readback. Shared deployments apply
their Grant and Policy admission as well.

Completed Artifact and Review records retain their original digests and
provenance. Read their exact identities; refresh evidence when evaluating a
claim about the current source or running system.
