# Work and Review adapter candidate

Work revisions preserve their prior intent, source baseline and assigned Slot in
the Domain's `work_item_revisions` ledger. Revision and handoff commands reject
running work, unresolved delivery, active resource ownership and uncertain
protected effects. Source handoff observations retain their `sender_reported`
scope and explicit push/receiver-sync fields. Completed signed execution
receipts can still be verified after responsibility moves to another Slot;
new receipt admission continues to require the current WorkItem binding.

`request_review` requires an explicitly selected Reviewer collaborator handle
in `reviewer_requirements`. It captures one candidate's complete recorded
evidence-ID set and the current reviewer-assignment revision. Optional
`evidence_handles` lets the caller choose that set explicitly; the full candidate
inventory remains sealed and unselected records are disclosed. A passing Review
must disposition every excluded record. Component-only records can retain an
out-of-scope explanation; adverse records require selected verified replacements
and the Reviewer's explicit resolution. Changed inventory invalidates Review
submission or later acceptance. The Runtime does
not select the reviewer. `submit_review` checks authenticated identity,
assignment, Work revision, the exact evidence set and candidate. A passing
decision additionally requires clean current SourceBinding readback and actual
CAS verification of every complete signed evidence bundle. Findings and
unresolved items must be resolved before a passing decision.

The Domain Review ledger supports a bounded unique set of up to 32 Evidence
records. Producer/observer independence is checked for every member. Acceptance
still requires one candidate, the exact reviewed evidence set, current Grants
including their delegation ancestry, verified artifacts, protected-effect
readback and the existing readiness/finalization checks.

`accept_work` requires an independently configured Finalizer authorization. Its
decision is explicitly `acceptance_ready` or `accepted`; no body field grants
that authority. Review submission itself does not change accepted state.
The integration tests exercise finalization only in isolated test schemas with
an explicitly created fixture Finalizer. The actual project owner's
confirmation, accepted revision, merge and Release remain separate decisions.

Current implementation exposes Work/Review/evidence reads and activity through
the same authenticated project adapter. Route creation and its separate Scope
admission remain an outstanding implementation item.
