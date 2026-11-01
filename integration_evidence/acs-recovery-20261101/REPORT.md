# ACS v2.0.1 production recovery verification

Verified 2026-11-01 (Asia/Tokyo). Product source is commit
`99124215300fd69de3ce7e088ca4dd1c19e65c0a`, tree
`8489200e1071710d1147fc24d68422f646f072f7`, merged through
[PR #19](https://github.com/D1ChangGeng/Agent-collaboration/pull/19).
The v2.0.1 verification below covered the existing WSL Owner Runtime and
selected remote receiving node. Later patch adoption is identified separately
in the follow-up section; earlier restart observations retain their version.

## Actual defects and changes

A pidfd-bound SIGKILL of the exact WSL owner maintenance process caused its
Windows task to finish with a nonzero result. It remained Ready beyond its
configured retry interval. The Windows operational log classified the action
as completed. Scheduler configuration alone did not restore the process.

The GUI host now retries failed WSL children after 30 seconds while keeping
the task running. A successful maintenance exit still ends it, including an
explicit owner startup disable. Repeating the process fault produced a new
maintenance PID automatically. No manual task start was used for that recovery.

The installer now resolves an existing task's name from its verified receipt
and restores managed availability/retry settings. A duplicate created during
reproduction of the old naming behavior was removed after verifying both
receipts, actions and executable hashes. The original task remains unique.

The remote Receiver also recovered automatically after an exact idle process
was killed using a pidfd. Existing systemd policy restarted it once; TLS-pinned
health observed a new real idle Codex Session. This verifies process recovery.

## Actual WSL instance restart

After both installations were upgraded, the selected Ubuntu distribution was
terminated. A subsequent Windows listing showed no running distributions.
Only non-starting Windows queries were used until Ubuntu appeared running
again. The original GUI host stayed alive and automatically relaunched its
owner maintenance process.

The distribution's PID 1 start identity changed. Its shared WSL kernel boot ID
did not change, so this is distribution cold-start evidence, not a Windows or
whole-kernel reboot. Read-only observation then found production PostgreSQL
and Temporal healthy, the owner maintainer present, all seven projects and
all 29 pre-patch sealed messages retained. Original application containers
also resumed. A test-only PostgreSQL container with no automatic restart
policy was restored separately after capturing the production recovery proof.

Windows reconnected through its original Codex MCP command and arguments.
Schema 2, the current communication catalog and project context were returned;
retired task tools were absent. No client configuration rewrite was needed.

## Independent real model communication

Nine new production request/reply exchanges were independently checked:

- Two Windows Codex requests invoked the actual remote Codex engineer.
- Four Linux OpenCode requests invoked that same receiving node, including
  a fresh model/MCP context after the WSL instance restart and v2.0.1 install.
- Three Windows Codex A / physical remote OpenCode B exchanges used
  `message_only`, including two after the WSL restart. B independently read
  Inbox through its ordinary engineer MCP, then called `send_message` with
  the original sender and explicit `reply_to`. The controller supplied B
  neither message content nor message handle.

Each verified request has exactly one matching-author explicit reply. Invoke
requests each have one Native attempt; all three `message_only` requests have zero.
Fresh clients read earlier messages and retained replies. In the final direct
exchange, A's actual `send_message` and `wait_for_response` results were both
`satisfied`; B's six normal ACS tool calls completed. Native terminal output
was never projected into a reply.

The first isolated OpenCode run changed HOME and had no ACS tools; it created
no message and is not counted. Some chat-compatible Provider attempts emitted
empty arguments, which ACS rejected. One later corrected its arguments and
completed; the first physical OpenCode B attempt stopped without replying.
The successful physical B profile used the existing Provider through a
child-only Responses adapter, consistent with [OpenCode's Provider guidance](https://docs.opencode.ai/docs/providers/).
Global Provider/model/plugin settings were retained. The selected remote
OpenCode and Codex ACS descriptors now use the v2.0.1 ordinary engineer entry.

## Upgrade and data preservation

The automatic updater correctly requested review because the protected tool
catalog had different line-ending bytes. All protected files were compared;
the only difference was that catalog's line endings. The existing authorized
guided upgrade path then installed the published patch. Automatic compatibility
checks were preserved.

The remote upgrade used a new verified wheel prefix and actual service-stop
evidence. The existing Node key signed the next Endpoint registration and
receiving generation. The owner transport adopted that actual generation.
Node/Runtime/Slot identities, signing/TLS keys, credentials and Journals were
retained. The remote engineering Git checkout remains on its prior branch;
its Runtime installation is separate and no automatic Git pull is claimed.

Read-only comparison preserved all pre-patch sealed packets, 2,528 command
deduplication rows, 20 Grants, seven projects, 15 communication messages and
seven reply links. Later verification exchanges append new records. The DSN,
credential, caller context and configured startup identity were retained.
Private backups and detailed fingerprints remain on their selected hosts.

The final strict installation check detected three Python cache files in each
retained receiver prefix. The diagnostic OpenCode test helper had imported its
process supervisor from those prefixes without disabling bytecode writes.
Every registered file hash was unchanged. Only those identified generated
caches were relocated to private artifact folders outside the immutable
prefixes. The helper now disables bytecode before import; the strict checker
and manifest were retained. Both old and active installations passed again.
After restarting only the owned Receiver, a ninth real exchange exercised the
fixed helper. Its associated reply and actual satisfied wait were checked,
and the active installation's 118 registered files passed the official check
again after that model run. WSL's 1,002 declared release files and the official
Windows startup check also passed.

## Tests and published bytes

- Native Windows tooling: 257 run, 220 passed, 37 platform skips. Its five
  Windows recovery checks include compiled child retry/success, executable
  admission, PowerShell parsing and recorded task-name preservation.
- Actual Linux startup/lock-handoff tests: 19 passed.
- Both candidate CI runs passed, including Runtime components, PostgreSQL
  integration, Gate tooling, Python 3.9/3.11/3.12 validation and packaging:
  [PR run](https://github.com/D1ChangGeng/Agent-collaboration/actions/runs/41243017193),
  [push run](https://github.com/D1ChangGeng/Agent-collaboration/actions/runs/41242975516).
- Existing release preflight passed. All five published v2.0.1 product assets
  were downloaded and matched the local candidate byte-for-byte and by SHA-256.
- Five fresh read-only Windows-to-WSL test PostgreSQL connections passed after
  cold recovery. This does not establish the cause or permanent absence of
  the earlier intermittent connection failures.

## Remaining qualification

The remote host was not rebooted. Noninteractive sudo required authentication,
and a user-requested occupancy audit found other accounts with active compute
workloads. The user then requested skipping this host reboot for the present
delivery. Shared recovery logic is covered by the WSL distribution restart;
the remote node's own process recovery, service restart, enabled unit and
lingering-user configuration were separately checked. This supports the
software delivery without claiming the remote host's complete boot path was
tested. Whole-host reboot remains not run and is no longer a release blocker.
Any future physical reboot requires an agreed idle window and authenticated
administrator action. User/account details stay private.

All Shared/restricted Native profiles, all host/Harness directions, Windows
login/reboot and sustained high load remain outside this qualification.
Credentials, private message handles, raw model reasoning and backups are not
included in the public evidence.

## Follow-up: v2.0.2 patch adoption

Both selected services adopted the published v2.0.2 commit
`7c72faf36dff2ec9d0cab2ade7bcd883aa68b5bf`. Its product assets were downloaded
and matched the frozen candidate byte-for-byte. The first automatic update
returned a generic failure and retained v2.0.1. Retrying the same automatic
path with the same strict guards activated v2.0.2; the original transient
failure's cause was not established. A final update observation was up to date.

The first post-update message was rejected before Native because an old
long-lived sending entry combined the new registered Endpoint with its older
in-memory receiving generation. The receiver fence remained intact. The
failed original message was retained and not blindly replayed. Only old,
owner-bound ACS entries matching their exact version/configuration and process
identity were reconnected. A distinct new normal verification then completed:
one actual Native attempt and one explicit matching-author reply. No unrelated
service or whole host was restarted.

A fresh connection through the original Windows MCP descriptor returned the
new missing-`project_id` and range guidance. Invalid calls created no message,
and history remained readable. WSL's 1,005 declared source files and the
receiver's 118 registered files passed strict integrity checks. All pre-patch
35 sealed packets, 2,537 command-dedup rows, 20 Grants, seven projects, 21 natural
messages and ten reply links remained. Credentials, caller context, storage
and startup identity were retained. The config-refresh defect is handled by
the subsequent patch and must be separately validated on a retained connection.

## Follow-up: v2.0.3 retained-connection validation

Both selected services adopted the published v2.0.3 commit
`f928cdad2eb8b2ba35bc6d47049442757b5569f6`. All five product assets were
independently downloaded and matched the frozen candidate. One initial
download error was retained; a retry succeeded before activation. Both CI
flows and the existing release preflight passed. One first CI attempt had an
unrelated simulated Codex RPC timeout at its unchanged 0.2-second budget;
the exact local Linux case and the failed-job rerun passed. Its transient
cause was not established, and the original failure remains in CI history.

After owner activation, only entries still executing old ACS code were
reconnected once. An actual Windows MCP client then initialized, read current
status and retained that same connection while the remote Receiver and the
trusted receiving configuration moved to the next signed generation. The
client was not reinitialized after that change. It submitted one ordinary
invoke request and received the real Codex engineer's explicit associated
reply; its actual send and repeat wait both returned `satisfied`.

Independent read-only evidence found one request, one correct-author reply,
one Native attempt, and the new generation on all prepare/readiness/dispatch
admissions. A is a scripted ordinary MCP application client in this specific
warm-connection check; B is the real Native model. This is not counted as a
new two-model A/B experiment. Earlier two-model evidence retains its own scope.

After the model run, WSL's 1,007 declared release files and the Receiver's
118 registered files passed strict integrity checks. All pre-patch 38 sealed
packets, 2,543 dedup rows, 20 Grants, seven projects, 24 natural messages and
11 reply links remained; the new verified exchange appended records. Identity,
credentials, storage, keys and startup configuration were retained. No host
or distribution reboot was performed for either patch follow-up, and the
previously requested physical-host exclusion remains in force.


## Follow-up: v2.1.0 qualification adoption

Both selected services now run the published v2.1.0 commit
`71c29114dd49a242a58d1ea30496497fa9cef453`, tree
`622c1f893fd6c8a0bc74a6b448c4046b4d8fba9d`. The five product assets and two
synthetic qualification summaries were independently downloaded and matched
the frozen candidate byte for byte. Both final CI flows and the completed
release preflight passed. Earlier failed qualification/CI attempts remain
recorded with their actual scope.

The WSL owner installation retained its machine/account binding, storage,
credential, context and startup identity. The selected idle receiver adopted
its staged prefix with the next signed generation, retaining keys, journals,
ordinary credentials and client configuration outside the versioned MCP entry.
Only the proven owned ACS service cgroup was stopped; its old process was
observed exited and the group empty before generation 6 activation. No whole
host or distribution restart was performed.

An actual MCP connection was initialized before the receiver cutover and kept
open while its trusted receiving settings moved from generation 5 to 6. It was
not reinitialized. That same connection submitted one natural invoke request,
received the real Codex engineer's own explicitly related MCP reply and observed
`satisfied` again on a repeat wait. A is a scripted normal MCP client in this
production check; B is the real Native model. The separate isolated
qualification contains the two-model physical and Shared experiments.

Independent read-only database evidence found one request, one correct-author
reply relation, one Native attempt, and generation 6 on all prepare/readiness/
dispatch admissions. The delivery reached `runtime_acknowledged`. The Native
returned to its actual idle Session after the exchange. One post-model health
read timed out; a bounded read-only retry returned idle. Its transient cause
was not established, and no message or model invocation was repeated.

WSL's 1,017 declared release files and the receiver's 118 registered files
passed strict integrity checks. Every pre-upgrade sealed packet (40), dedup row
(2,548), Grant (20), Project (7), natural message (26) and reply link (12) was
preserved. The verification exchange appended records. Production retains its
15 historical WorkItems and task-era relations under the additive adoption
boundary. Both new packets are `acs-message/1` without task identity/revision
fields; both new events target messages with null WorkItem associations. The
old database remains connection-fenced and no historical data was cleaned.

The existing live connector independently returned Owner mode, authorized
communication core Schema 2, seven visible Projects and current project context.
The formal local source checkout was fast-forwarded, with both existing
five-line README edits restored and all untracked work retained.


## Follow-up: v2.2.0 Codex Shared and production adoption

Both selected installations run the published v2.2.0 commit
`a5142b2479f348c1fd5a90dfc660c5ac38ae378a`, tree
`8160fa13ea3faa55c3ea84c6cd4ca4c0f3e762b0`. The product and qualification
assets were independently downloaded and compared byte for byte. Exact-candidate
push/PR validation and the completed release preflight passed. The separate
[qualification](../acs-codex-shared-20261101/REPORT.md) records the real two-model
physical Codex Shared loop, OS permission probes, idle survival and immutable
1,800-second Windows-to-WSL transport run with 6,544 exchanges.

The WSL owner updater retained its machine/account, storage, credential, context
and startup identity. The physical receiver adopted its independently verified
staged wheel with signed generation 7. Only its proven owned ACS service cgroup
was stopped. Six original key/credential hashes, registration identity, ledger
and Driver/Node Journal paths remain unchanged. The ordinary client credential
was copied byte for byte; client configuration changed only its versioned MCP
entry. No host or WSL distribution reboot was performed.

An actual ordinary MCP connection initialized before receiver cutover and
submitted one natural invoke request afterward. Its first 300-second reply wait
expired. The request had one real Native ACK, not a reply. A replacement MCP
connection continued the original handle without any send or reinvocation and
received the real engineer's own explicitly related reply; repeat waiting was
also satisfied. A is scripted in this production check, B is a real Native
model. The independent two-model acceptance is the separate isolated experiment.
The configured xhigh model environment was preserved. A read-only provider
probe authenticated successfully and listed the selected model; the exact
latency cause was not established. The initial timeout is retained as evidence.

Independent database readback found one request, one correct-author reply link,
one Native Attempt and generation 7 on every signed prepare/readiness/dispatch
admission. Delivery reached runtime_acknowledged. The actual Native Session
returned to idle. Both new packets are acs-message/1 with no task identity or
revision fields; both new events target messages with null task associations.

All 1,024 WSL release files and 119 registered receiver files passed integrity
checks. Every original sealed packet (42), dedup row (2,553), Grant (20), Project
(7), natural message (28), reply link (13) and historical WorkItem (15) retained
its fingerprint. The check appended records: 44 sealed packets, 2,558 dedup rows,
30 messages and 14 replies; Grants, Projects and historical WorkItems stayed at
20, 7 and 15. No data cleanup or irreversible migration was performed. Precise
scope and counters are in the JSON; production handles, credentials and model
reasoning are excluded from the public additions.
