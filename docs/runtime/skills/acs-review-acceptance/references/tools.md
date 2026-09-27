# Review and acceptance tool map

- list_reviews discovers assignments and completed decisions.
- request_review creates a baseline-bound Review.
- submit_review records structured decision and findings.
- list_evidence and read_resource inspect supporting claims.
- read_source and read_diff establish the candidate inspected.
- accept_work commits accepted state at the authorized boundary.

Reviewer and Finalizer Profiles expose only the reads and mutations admitted by
their Grants.
