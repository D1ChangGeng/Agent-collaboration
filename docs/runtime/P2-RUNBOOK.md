# P2 two-machine execution runbook

Status: preparation only. Every P2 scenario is `NOT_RUN`. The checked-in
inventory binds only the stable Machine IDs `windows-local` and `linux-1302-1`
and their host labels. It intentionally contains no source commit, tree, host
fingerprint or component version claim. `p2_harness.py init` reobserves the
current local physical Machine and exact Git HEAD/tree; the remote Machine must
be freshly observed by the later execution run. Historical a97/912 checkout
facts are not current inputs.

## Execution order

1. Finish and independently accept P1 on one exact integrated commit/tree.
2. Synchronize both clones to that exact commit and verify clean tracked state.
3. Enroll both physical Machines and Nodes; record fresh machine/session
   observations, actual Harness/Driver versions, and the selected Codex
   authentication mode. For the current profile, verify the `zeo-dev` API
   provider by a redacted fresh probe; do not require OAuth login.
4. Deploy the authenticated TLS receiver and supervised Node on Linux. Verify
   the presented certificate, current registration and systemd/cgroup state.
5. Execute all eight `P2-CODEX` scenarios and independently review that Gate.
6. Execute all eight `P2-OPENCODE` scenarios, including Human Bridge, and review
   that Gate. A P2-CODEX component result cannot satisfy an OpenCode scenario.
7. Implement and execute the P2-MCP-WORKFLOW surface through real Codex and
   OpenCode MCP clients.
8. Execute P2-MANAGEMENT-WORKFLOW through local and remote web-capable MCP
   clients, including ProjectContextPack, Source reads and Skills.
9. Execute [P2-CONTROL-PARITY](P2-CONTROL-PARITY-CONTRACT.md) for Web receiver
   wake and Root-managed handoff acknowledgement.
10. Perform the complete P2 independent review and retain the product-owner
   decision boundary.

Each scenario must produce its own command, operation, message and event IDs;
receipts; raw output; fault injection; source, artifact and effect read-back;
recovery trace; observer/owner identities; exact binding digest and zero
unresolved items. Reused P1 evidence proves only the prerequisite.

## P2-CODEX

- `TWO-MACHINE-LOOP`: send Windows→Linux and Linux→Windows over the registered
  TLS receiver path. Record both physical host fingerprints, Node IDs, sessions,
  request/response receipts and one native invocation per direction.
- `UI-EXIT`: after durable dispatch, exit the selected Codex UI and prove Core,
  Node and receiver continuity independently from the UI process.
- `NETWORK-PARTITION`: first put long-running work in tmux. Apply a bounded
  partition only to the tested receiver route, preserving SSH control. Record
  before/during/after routes, deadlines and reconciliation.
- `NODE-RESTART`: restart only the enrolled Node unit; bind old/new boot and
  generation, supervisor proof, local journal and Domain recovery.
- `SESSION-REPLACEMENT`: replace the target Codex session while preserving
  Route/AgentSlot/WorkItem/message identity. Record both session observations.
- `ACK-LOSS`: drop the post-commit ACK, read back Inbox/receiver/Domain state and
  prove no second native invocation.
- `STALE-OWNER`: replace the lease owner and exercise the protected resource
  gateway with the stale fencing token. The stale effect must be rejected.
- `UNCERTAIN-EFFECT`: interrupt after an external effect marker; perform actual
  resource read-back before adopting, compensating or retrying.

## P2-OPENCODE

- `CROSS-HARNESS-LOOP`: Codex→OpenCode request and OpenCode→Codex response with
  exact session, Driver and receipt identities.
- `CAPABILITY-PROBE`: record scoped capability observations, expiry and refresh;
  unknown or stale capability cannot select a transport.
- `TRANSPORT-SWITCH`: fail the pinned transport, exhaust its bounded recovery,
  then select another eligible provider while preserving logical message ID.
- `LIFECYCLE-RECOVERY`: restart/replace the OpenCode process and session after
  dispatch; recover from native read-back without a second invoke.
- `PERMISSION-DATA-POLICY`: exercise revocation and source/artifact/effect
  authorization at the actual protected boundary.
- `LATE-DEDUP`: inject a late duplicate after the winning response and prove it
  remains audit-only.
- `HUMAN-BRIDGE-RECOVERY`: prove all automatic paths exhausted, emit one local
  notification effect, receive one authenticated manual return, and race it
  against successful re-probe. Manual content never grants authority.
- `SOURCE-ARTIFACT-EFFECT-READBACK`: independently read exact source tree,
  artifact digest and protected effect result from their real authorities.

## P2-MCP-WORKFLOW

- TEAM-CONFIGURE: configure AgentSlot, role, Grant, Policy and budget bindings
  inside an existing Scope through configure_team.
- HARNESS-LIST: execute list_harnesses with scoped, unexpired capability
  evidence.
- SEND-ASYNC: use default asynchronous send_message and return stable response
  and notification handles.
- SEND-SYNC: observe the same response through bounded wait_for_response.
- BOUNDED-WAIT-CONTINUITY: retain tracking across timeout and MCP reconnect.
- TARGET-IDLE-DELIVERY: commit a busy target Inbox item and invoke after idle.
- COMPLETION-NOTIFICATION: deliver one deduplicated completion notification.
- SESSION-CONTINUITY: route completion to the current replacement Session.
- RESOURCE-MESSAGE-INBOX: prove pure resource reads, Message consumption and
  Inbox listing as independent contracts.
- TYPED-CONTROL: exercise notification, WorkItem and Runtime Attempt controls.
- WAIT-AGGREGATION: exercise any and all response conditions.
- SKILL-KNOWLEDGE-ROUTING: route material questions to one knowledge domain and the smallest applicable reference.

## P2-MANAGEMENT-WORKFLOW

- PROJECT-ADOPTION-IDENTITY: preserve Project and Root identity during setup.
- PROJECT-ID-ISOLATION: reject a mismatched project_id and typed handle.
- LOCAL-CONTEXT-HYDRATION: load current AGENTS, manifest and source identity.
- WEB-CONTEXT-HYDRATION: load a complete ProjectContextPack remotely.
- CROSS-PROJECT-LIST: enumerate multiple authorized projects independently.
- ROUTE-WORK-COLLABORATOR-LISTS: return stable handles and revisions.
- EVIDENCE-REVIEW-LISTS: discover Review and Evidence resources.
- FILESYSTEM-SOURCE-READ: list, search and read files, source state and diff.
- EXTERNAL-SOURCE-COORDINATION: bind external provider reads to ACS source
  identity and revision.
- WEB-REVIEWER-FLOW: perform exact-baseline Review from a web MCP client.
- WATCH-INBOX-RECOVERY: deliver subscription change and recover it from Inbox.
- SKILL-CONTEXT-PRESENTATION: prove metadata-first discovery, selective references, knowledge hints and ProjectContextPack integration.

Public MCP bytes, profile-filtered tool discovery, exact arguments, Domain rows,
Inbox and Outbox, Source readback, OAuth scope, Node and Driver observations,
Skill metadata, loaded references, knowledge hints, Session activity and unresolved items are direct Gate evidence.

## P2-CONTROL-PARITY

- WEB-RECEIVER-WAKE: a program Harness addresses a current web AgentSlot and
  proves native web Turn start or resume, not merely Inbox recovery.
- HANDOFF-ACK: an authorized Root Agent hands existing Work to an already
  addressable B Slot; B's authenticated, exact-handoff response closes the
  pending acknowledgement after Inbox commit, without duplicate handoff or
  silent owner drift. Root can explicitly withdraw an unanswered intent.

These are focused capability probes. See the
[Gate contract](P2-CONTROL-PARITY-CONTRACT.md) for the exact preconditions,
receipts, readbacks and authorization boundaries. Prior Web reads, Web
create_work, project Inbox consumption and older-baseline Runtime Gates retain
their original scopes and do not by themselves pass this Gate.

## Fault safety

This package contains no firewall, service-stop, login or credential commands.
Network/service fault injection requires a separately reviewed command packet,
active tmux control session, explicit target/timeout/rollback, and pre/post
read-back. Evidence output belongs in private storage outside the source clone.
