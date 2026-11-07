# ACS P0/P1/P2 development objective

The user requires every development capability, excluding qualification coverage
as a stopping prerequisite. DEVELOPMENT IS COMPLETE; the final audit and current
regressions are finished. See FINAL_REPORT.md and development-capabilities.json.
Source delivery on the existing branch is documented separately in PUBLICATION.md;
the verification baseline below remains its original pre-commit observation.

Repository D:/Chatgpt/Agent-collaboration, codex/core-cleanup,
HEAD19d7881d49ee887315c54c5bc02e0cc424061376, dirty/uncommitted/unpushed.
Preserve all existing code/research/worktrees/evidence. Single Executor session;
no subagents, real-contact messages, production changes or model calls.

Implementation gaps C06/C07/C16/C17 are closed in source:

- Exact stopped original Native transport restore and durable Node/profile
  reconstruction: signed current Core authority, original process/session/
  generation, journal/claim/account/environment fences. Same-session unknown
  input can reconnect for query only; no new input or replacement session.
- Same Message resumes its context repeatedly, retaining lifecycle cycles in
  its existing Outbox. Archived Core facts also prohibit namespace reset.
- Authenticated remote provenance reader uses existing signed TLS readback.
  Current participant ACL/registry and receiving-node read policy bracket every
  outcome, including cache and unavailable results; no caller path/Host grant.
- ExistingOrcaReceiverBackend/OrcaReceiverRouter reuse the actual verifier and
  prepared/dispatch ledger. Explicit serialized Host callbacks and original ACK
  lookup only; no Driver/PTY takeover, duplicate ledger or verifier-only RPC.

Current regressions:
- final-restore-source-components:284passed,1 inapplicable OpenCode-only skip.
- remote-source-current-read:28passed.
- orca-core-remote-source-c:2 actual Core/PG/TLS/remote-reader composition passes.
- restore-factory-core-b:5 Core attestation/history/Message-cycle passes.
- development-static:10 checks pass (pack/contracts/Ruff/diff/SDK/strict TS).
- package-facts:191 source/wheel/temporary installed files match.

Raw earlier failures are retained. Remote source a/b needed actual endpoint
rebind after replacing the configured descriptor. Factory a lacked its explicit
spy's journal member. Corrected cases pass with original safety assertions.

No runner or PG lease is active. The broad development-final-integration batch
was stopped after two fixture classification failures; its interruption and a
focused failure stack remain preserved. The wire fixture now separates original
session reads from mutations, still forbids additional writes and checks exact
read targets. wake-lost-ack-regression-b:31passed. Current final actual-service
combination development-final-integration-b:76passed,0skip,0failure, unchanged
captured source. It includes all35 API operations and installed maintenance.
development-static-b:10passed; SDK210passed and strict TypeScriptpassed.
Source/wheel/isolated-installed191files match. Test DB was only the named local
acs-communication-test-20261031 / acs_communication_test; no production changes.

Remaining development items:0. Audit covers all25 C,40 R,35 APIs and30 UI/source
contracts; canonical adoption-state points here. qualification-matrix.json
separately retains source-stale Native E3/E4 history and pending actual Orca,
physical two-machine and unmeasured platform/profile qualification. These are
verification surfaces, excluded by the user's development stopping condition.
No commit/Push/deployment. Production and existing configuration/data untouched.
Do not run old finish_revision_reports.py or prepare_revision_artifact_facts.py;
they restore the earlier narrow scope and stale qualification claims.

Prior checkpoint text is preserved in WORK_STATE-before-final-audit.md.
