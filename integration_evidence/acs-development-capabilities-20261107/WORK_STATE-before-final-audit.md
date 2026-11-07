# ACS complete development-capability objective

Active user goal: finish all P0/P1/P2 development capability items, excluding
qualification/verification coverage as a stopping prerequisite. Do not substitute
the previously declared limited support set for this objective.

Baseline: D:/Chatgpt/Agent-collaboration, codex/core-cleanup,
HEAD19d7881d49ee887315c54c5bc02e0cc424061376, dirty/uncommitted/unpushed.
Preserve existing source, UI/research, worktrees and all old evidence. Prior
completion records remain historical acceptance of their declared scope.

Current role: Executor; single Codex session. No external ACS messages or
production changes are needed. Previous turn changed implementation/tests and
produced evidence, so it was progress. This new goal remains active.

Confirmed development gaps to close:

1. C06/C07: existing lifecycle resume requires a live owned process. Add safe
   stopped-process same-native-session restore through the original signed Core
   lifecycle command/DriverJournal/current-authority path. Preserve unknown-input
   fences; never substitute thread/start or POST/session for the original session.
2. C16/C21: original Native source lookup is mounted but accepts only a trusted
   local DriverJournal; add the authenticated remote reader composition using
   existing receiver trust/transport, with no caller-selected file or second ledger.
3. C17: distinguish the complete TypeScript protocol port from its missing
   concrete existing-Core verifier integration. Inspect and implement ACS-owned
   adapter/wiring; actual Orca installation/qualification is a separate surface.

Audit remaining unsupported/conditional branches against the25 change items and
activated detailed requirements. Physical two-machine qualification and
unmeasured platform combinations are validation gaps, not missing code by
themselves. Do not add unsupported generic Drivers or discard safety invariants.

Implemented in this goal turn (not yet overall complete):

- Codex/OpenCode now separate process-transport launch from Session creation.
  Signed resume can restart a proven stopped owned transport and reattach only
  the original Session. Process-stop evidence scopes the local operation ID;
  cached/lost ACK never repeats a launch. Restore never calls thread/start,
  POST/session or prompt routes.
- Same-session uncertain input may reconnect only for original-domain query.
  It remains uncertain and blocks fresh input until original reconcile; an
  uncertain creation or foreign Session still blocks restoration.
- Lifecycle capacity supports signed stopped facts without inventing Native
  readiness. Node leases permit exactly their journal-recorded new transport,
  then pin its actual client against callback-time replacement.
- Original Message wake can archive successful bootstrap cycles in the same
  Outbox and resume a stopped original Session repeatedly. It creates no new
  Message/recovery/Core operation; old positive/possible facts remain retained.
  Core namespace guards recognize archived capacity, preventing journal-loss reset.
- Durable stopped-origin/profile reconstruction is wired into both concrete
  factories. Requires a positive full-stop receipt, original known Native
  context, matching files/account/environment and original Core signed plan.
  No PID/name adoption or unproved process stop; missing trust remains unknown.
  Bootstrap flag can reopen an existing valid schema2 journal; lost journal in
  an existing namespace still refuses recreation.

New Runtime modules: native_restore.py, native_restore_origin.py,
communication_message_restore.py. Modified Drivers and existing lifecycle
contract/capacity/Node/issuer/factory paths. No SQL schema or new operation ledger.

Evidence: restore-baseline517pass/3platform skips; cold-restore-controller-a14pass;
cold-restore-transports-a20pass; message-cold-cycles-a35 actualPGpass;
durable-restore-c124pass. Native peers/OS stop observations are explicit doubles,
not E3/E4. New unknown-input tests initially expected wrong exception classes;
those failures remain in cold-unknown-domain-a/b, and current assertions are
included/passing in durable-restore-c. Durable origin a/b/diagnostic fixture
mistakes remain raw, all corrected in c. No model API call occurred.

Current work: C16 remote original-journal reader implementation. It reuses
delivery.readback, adds NativeSourceReadbackBody, Node bridge refs-only lookup,
authenticated RemoteNodeEndpointAdapter.read_native_source, trusted registry
RemoteNativeSourceReader and before/after Core ACL/fence checks. Current source
also adds Receiver source-read current auth, cached-result recheck and journal
I/O outside Receiver SQL transactions. No new RPC or caller-selected path.

Active runner: remote-native-source-a, session15672, component/controlled native
protocol only, no PG/model. Do not mutate runtime/tests/sdk while it is running
because .tmp/run_development_capabilities.py captures all source bytes.
Check its terminal state/result before rerunning. Other old runner handles:
45930/16969 terminal failures (diagnosed fixture mistakes),29060 terminalpass,
74479/26384/84735/61550/73220 already drained. No PG lease or Native model process.

Next actions:

1. Finish C16 source tests (current test_remote_native_source.py), actual TLS
   transport and real Core facade/registry composition. Fix failures rather than
   reducing assertions. C16 implementation is not complete merely because its
   protocol methods exist.
2. Finish C17 actual existing-Core verifier adapter and bounded host-receiver
   composition. Existing TS port remains complete, actual Orca installation is
   a verification/deployment surface. Do not invent verifier-only RPC routes,
   use ordinary Orca mutation RPCs as atomic admission or own the Host PTY.
3. Add final current checks for factory reconstruction/Core profile attestation,
   Message cycle history/namespace isolation negatives, then audit every25 C and
   activated detailed R to ensure zero development-capability omissions.
4. Update canonical development state (adoption-state.json was reopened to
   partial C06/C07/C16/C17; prior scoped report is historical, not this goal's
   definition of done). Do not run old finish_revision_reports.py: it would
   overwrite the active full-capability state with the old narrower scope.

Goal is ACTIVE, not complete/blocked. No push/commit/deployment or real user
messages. Models are not needed for initial implementation. Use the named
isolated test DB only, serial PG suites. No subagents are authorized in this goal.
