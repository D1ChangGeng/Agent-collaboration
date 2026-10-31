# ACS v2.0.1 production recovery verification

Verified 2026-11-01 (Asia/Tokyo). Product source is commit
`99124215300fd69de3ce7e088ca4dd1c19e65c0a`, tree
`8489200e1071710d1147fc24d68422f646f072f7`, merged through
[PR #19](https://github.com/D1ChangGeng/Agent-collaboration/pull/19).
The existing WSL Owner Runtime and selected remote receiving node both run
the verified v2.0.1 release.

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
