# Source and evidence decision map

Use the local filesystem provider for current workspace edits, admitted
untracked files, Management Root content and machine-bound evidence. Use a
repository provider for remote refs, committed snapshots and pull-request
context. Compare exact commit and tree when both providers describe the same
repository.

Use a current owner workspace view to inspect active changes. Freeze its view
revision for delegation, Review and acceptance so the inspected bytes can be
read again. Use an explicit commit snapshot for a committed baseline. Record
workspace view identity and Git commit/tree as separate facts.

Capture source state before source-dependent delegation. Handoff reports branch,
base/head, tree, workspace state, commits, Push and receiver action. Acceptance
uses the integrated source actually read back.

A digest proves byte identity. Execution receipts and independent Review
establish what those bytes support. Preserve completed historical records when
an earlier Grant naturally expires; check current credentials, explicit
revocation and target ownership before a new read or action.

Report imported or endpoint-reported facts with their actual provenance.
Refresh source and process observations when the claim concerns current state.
