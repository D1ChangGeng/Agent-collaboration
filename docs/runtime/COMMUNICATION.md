# ACS communication contract

Implementation authority: the user-authorized development package v2.33,
`RFC_TEMP_SOURCE/ACS_Development_Package_v2.33/CODEX_START.md`. That number is a
document version, not a software release. Current engineering evidence is in
`integration_evidence/acs-communication-20261031/`.

## Normal use

1. `list_collaborators(project_id)` returns your stable address and contacts.
2. `send_message(project_id, to, content)` sends natural text. Use the same tool
   for introductions, questions, corrections, replies and handoffs. The default
   is `activation="invoke", response_mode="async"`.
3. `check_inbox` discovers incoming messages; `list_messages` also finds outgoing
   history. `read_message` returns original text, authors and relationships.
4. Reply with the original sender as `to`, and the original `message_handle` in
   the `reply_to` array. One reply can cover several requests from the same peer.
5. `wait_for_response` observes original message or response handles. `sync`
   sending uses the same observation after committing. A clarification counts as
   a reply. Native completion, system notices and unrelated messages do not.

`message_only` stores the message in the authoritative Inbox without starting
Native execution, even when no Native endpoint is configured. It can still be
combined with `sync`. A timeout bounds the observation, not the communication.
After reconnecting, use the retained handle; do not resend the request to wait.

Reading does not consume messages. `max_inline_bytes` and `offset` continue long
content; offsets are byte positions on UTF-8 boundaries. List cursors are opaque.
Use `next_cursor` for the next page and `resume_cursor` for later arrivals.
Changing a history query's filters resets its cursor. Authority commit order is
not an assertion about cross-machine clocks or Agent work order.

## Identity and permissions

Authors come from trusted transport configuration and live project/Grant
bindings. Message text and a supplied reference confer no permissions. Separate
Slots sharing a principal require distinct trusted `context.agent_slot_id`
bindings. `context.trusted_client=true` is an operator-established Client
capability, not a model tool argument. A Client can have a durable reply address
without a synthetic Root Slot or Native Session. Existing lower-level bindings
do not gain Client privileges by omitting a field.

Client, project Root and Route manager are the management levels. Operational
Grants remain scoped and live-checked; profile inheritance permits lower role
eligibility without inventing operational permissions. Ordinary Agents cannot
configure teammates. Names are display metadata; changing a name does not change
authors or reply relationships.

`configure_team` merges specified members and fields. It preserves omitted
members. `if_unchanged` checks an observed property's old value; an explicit stale
revision also rejects. Configuration commit, receiver preparation and observed
Native Session are separate results. Only a real bound Adapter may supply a
Session ID. An absent provider is reported as unavailable. `list_harnesses` is
read-only and never prepares, spawns, resumes or invokes a receiver.

Node observers can register a communication Runtime without task Attempt or
execution-result permissions. The production Codex receiver derives its own
identity from the enrolled Node, rechecks that enrollment, and separately checks
the committed sender. An unbound Client origin is recovered from the sealed
packet and stored Client registration. Preparation needs no result collector
or artifact directory. Retired task packets cannot start a new Native turn.

Local Native capacity supplies Node-authorized lifecycle configuration and readback
callbacks. Core does not invent a Driver operation identity to start or inspect
that Node. Without a verified callback, an existing binding is reported as an
unconfirmed binding record. Remote receivers retain admitted preparation and
actual Native health protocols.

An optional admitted `endpoint_id` selects a receiver already bound to the same
Slot; null restores automatic selection. Multiple eligible receivers require a
choice. Configuration returns actual `caller_bindings` for the existing trusted
stdio/OAuth provisioning mechanism. It does not expose credentials or accept
model-supplied sender identities. A changed profile requires the trusted caller
binding to be refreshed; stale bindings are rejected against current configuration.

## Persistence and Native effects

`delivery_messages.packet_json` holds authoritative natural text and identities.
`communication_messages` is its project/address/order index; `communication_replies`
indexes explicit relationships. Project serialization through commit prevents a
late lower sequence from being skipped by pagination.

Submission, reply indexing, request deduplication and Outbox creation share the
Authority transaction. A reused request identity with changed content rejects;
intentional identical messages remain distinct. A host retry should retain its
original `client_request_id`; the MCP ingress also derives an identity from the
connection and RPC request ID. A new connection needs the retained explicit key
or message handle; content similarity is not a safe retry identity.

The stdio and HTTP entry points maintain committed natural-message delivery.
Direct library users must run a dispatcher or the maintenance loop themselves;
the send result distinguishes that condition. Retries are bounded and a possible
Native dispatch is never blindly repeated. An active reply wait can receive the
same reply through its Tool Result without a duplicate Native turn. Inbox remains
available if that result channel disappears. Notifications are wake hints, not
proof of model consumption.

The configuring manager becomes a collaborator's direct communication manager.
Partial configuration preserves that relationship; configuration and contact
readback show the actual `manager_handle`. A trusted configuring Client can be
the top outlet without a synthetic Slot. Existing adopted contacts with no
configured relationship do not acquire an inferred manager from a profile name.

Definite communication obstacles produce system notices in that manager's Inbox
and queue one Native notification through its currently authorized binding.
`acs-notice/1` has an ACS source and its own durable operation identity; it does
not enter Agent message history or reply relationships, or expose the original
private message body. Only a definitely unreachable manager causes forwarding
to its own configured manager. Busy defers; acceptance stops automatic forwarding;
an unknown Native outcome stays unknown and is never replayed. A manager that
needs further help sends its own ordinary message. No reply timeout means repair
failure. The highest Client outlet retains the notice in its actual Inbox.

When the original message's Native outcome is unknown, its notice is retained
without automatically invoking a manager. When no configured higher outlet
exists, a unique actual Client or the sender retains the notice. Notification
readback separates the original obstacle from the notification's own Native
delivery state and never claims model consumption. Native result collection is
outside both the normal message and system notification paths.

## Adoption and history

New installation uses `communication_core_schema.sql` and Project schema 2,
plus the communication and notice/archive indexes. It creates 46 tables and
does not create the 36 retired task, result-projection or Watcher tables.
`DomainAuthority.initialize()` and `ProjectService.initialize()` remain explicit
operator steps; the latter can also adopt the known complete 1.13 baseline.
Normal startup validates current communication storage and reports
`project_schema_adoption_required` when adoption is missing; it never migrates
a deployment. Existing message and notification records remain intact.
Schema identity uses canonical LF endings. Explicit adoption recognizes only
the same SQL's known LF/CRLF forms, so a Windows checkout and a Linux checkout
can share the Authority; other checksum or version differences still require
an explicit migration.
The additive adoption retains existing records; it does not delete task tables,
guess old authors or manufacture reply relationships. Two delivery endpoint
columns become nullable for an Authority Inbox without a Native location.

Task tools are removed from the normal catalog. Generic CLI/MCP/HTTP commands
now declare only Node/Runtime/receiver registration, endpoint binding, permitted
message reads and delivery maintenance. Their exported schemas and parsers no
longer accept task reads/mutations, task Attempts, Lease/Effect, task Harness
bindings or execution-result projection. Default project adapters
no longer load task/Review/Watcher execution modules. Current `read_resource`
reads Project, Route, captured source and communication records; `list_activity`
uses current project configuration and actual message participants.

Explicit archive adoption indexes only stored historical project associations,
original principal references and recipient Slots in `communication_archives`.
Missing sender Slot or recipient principal stays unknown. Original packets and
stored Native artifacts keep their original meaning and their own permission
checks. Historical reads do not consume or update records, and old Native output
does not satisfy a current reply wait. Current reads use the archive index after
old task tables are retired. See [the operator procedure](COMMUNICATION-ADOPTION.md).
The default Domain facade no longer has Work, Review, execution receipt, task
Attempt, Lease/Effect or task Harness-binding methods. Historical seeding and
regression methods live in test fixtures excluded from the Runtime wheel.
Delivery rejects new legacy packets; operator scan/dispatch services process
current communication packets only. Existing operator `effects` settings can be
read during adoption but do not construct a task gateway. New installation
Grants do not request the retired business permissions. The retired task Human
Bridge console command is no longer installed.

Existing mixed 1.13 storage retains its old tables and original metadata record.
The current core has its own `acs-communication-core/1` metadata. Known Project
schema 1 is explicitly adopted to version 2. Unknown versions/checksums and
unversioned existing storage refuse adoption. Missing authority ledgers or
critical unique fencing indexes require actual recovery, rather than empty
replacement. Retired DDL and its old migration helper live in test fixtures and
are excluded from the Runtime wheel. Some unbound historical modules remain;
production cleanup requires its current inventory and applicable authorization.
An old binary is not a promised rollback
after new messages have been written.

## Verification and supported claims

The focused suite uses an explicitly named, disposable PostgreSQL database and
normal authenticated tools. Two actual stdio MCP processes and independent Codex
model contexts were exercised. The first real model run used two ordinary Slots
on 1302-1 and `message_only`; it does not certify Native autoactivation or a
cross-Harness matrix. See the implementation report for exact source bytes,
commands, negative cases, retained failures and outstanding checks.

An optional `with` peer filter may be omitted or supplied as an empty string;
both select the same unfiltered view and use the same continuation cursors.
A nonempty value must be an actual collaborator or Client address. This matters
for Harness adapters that populate optional string fields automatically.

The production Windows Codex receiver factory has also been exercised with
actual Node/Runtime enrollment, independent A/B contexts, automatic Native
activation and B's own MCP reply. This qualifies that local tested setup; it does
not certify a physical cross-machine Native activation matrix.

Windows Codex and Linux OpenCode on 1302-1 have now exchanged a natural request
and an explicitly associated reply through their own ordinary authenticated ACS
MCP tools. This uses `message_only`, a shared isolated Authority and a loopback
SSH database forward. It qualifies that communication direction, not signed
cross-machine Native delivery or OpenCode receiver autoactivation. The first
failure exposed the empty-filter bug; original failed and corrected model runs
are retained in [the cross-Harness evidence](../../integration_evidence/acs-cross-harness-20261031/REPORT.md).

The default Domain cleanup, current-source Native and cross-Harness reruns,
and actual installed wheel are recorded in [the kernel evidence](../../integration_evidence/acs-surface-retirement-20261031/REPORT.md).

The 46-table storage and explicit adoption are recorded in [the storage evidence](../../integration_evidence/acs-storage-20261031/REPORT.md).
Native context `acs-native-context/1` includes the actual Project and an optional
reply/read action directed to ACS MCP. These arguments retain opaque ACS handles
and leave reply content to the recipient. Native sub-agent messaging has its own
address space. The MCP initialization instructions explain the same distinction
for senders and clients using deferred tool discovery.
