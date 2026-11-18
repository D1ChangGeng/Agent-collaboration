# Porpita desktop delivery — active

Objective: PRODUCT_ACCEPTED under Porpita-Codex-Ready-Development-Package-v1.0.0.
Current product acceptance: **PRODUCT_ACCEPTED**. All 22 required scenarios passed against installed Windows x64 Candidate 11. See handoff/DELIVERY_REPORT.md and delivery-manifest.json.

- Candidate 09 installer SHA-256: `7e18169791e6c6373084895486714288f56229888be6bfed3fccee2ff765917f`. Its evidence includes ordinary first contact, real native approval and follow-up, paired worker settlement, remote file byte equality, and isolated existing-service login.
- Candidate 10 staged source tree: `8f66f72cc6df4f90e02e874c0535553eeac38f4f`. The exact patch reproduces that tree in an isolated Git index. The corresponding ACS source is `c6bf795be35cc1db8a444ff07837a46009ae99e0` in the isolated delivery checkout.
- Bundled ACS 2.3.1 wheel for 10: `a4deca4bc03473d4972c72a53cf6e3dde07cc541b6bc28323b5c5c0b2e9f2ec4`. Two real PostgreSQL regression tests passed for the newest page and old cursor behavior. The replaced generated runtime backup was removed.

## Source and ownership

- Client: D:/Chatgpt/Porpita, branch codex/porpita-desktop.
- Adopted Orca: 26179069b664b2fc172963564ed419d97892b6c9, package 1.4.214.
- Product version 0.1.0; independent io.github.d1changgeng.porpita identity.
- ACS: D:/Chatgpt/Agent-collaboration, main e5d71968a13e67e3dc51e318867d4ed9a1f946ac.
- Existing ACS tracked edits and untracked prior evidence were preserved.
- Client changes are uncommitted; no Porpita origin supplied; no push or public release.
- No subagents were used. Execution is one session on Windows x64.

## Actual implemented increments

Independent complete upstream source; original native UI/workspace/terminal/editor/Chat code retained.
Product identity, SVG/PNG/ICO/ICNS/tray assets, data-root and public CLI adaptation in progress.
Upstream update and telemetry transport disabled; account/publishing/push/diagnostic defaults isolated.
Existing ACS SDK adopted under src/shared/acs with source/output digests and separate license.
Human collaboration Host RPC is registered in the inherited generated shared catalogue.
The Settings/onboarding connection form invokes real ACS via the Host; credentials use inherited safeStorage.
Managed local Python/PostgreSQL/ACS startup, private state and quit integration are implemented.
Per-native-session Core identity/MCP composition is wired to existing Codex app-server and ACP launches.
Actual signed ACS Node/Runtime/Receiver enrollment is composed in porpita_receivers.py and
porpita_receiver_enrollment.py. A private loopback Host bridge uses the existing structured Host,
current child object/generation, serialized final handover and original native journal settlement.
Native journal provenance is persisted across journal row/outcome formats; pending is not a Native ACK.
Installed-system OpenCode 1.4.6 is too old for the adopted Host (minimum 1.18.31); it was preserved.
Official OpenCode 1.18.31 and Codex 0.166.0 Windows binaries were separately prepared under
resources/porpita-runtime/windows-x64/harnesses, with archive/executable hashes and licenses.
The existing settings/onboarding now offers actual private Harness preparation. The selected OpenCode
profile contains copied credentials only, never the original conversation database. Its two tests plus
four existing enrollment-persistence tests passed. Bundled Codex selection is wired on Windows x64; installed first-run and fresh sign-in remain unmeasured.
Product-owned hook paths and endpoint environment coordinates are namespaced for coexistence.
The focused hook matching suite passed 3 tests. The complete hook test file also has Windows
symlink privilege and fixed Git Bash path failures; those are not claimed as passing.

## Verified feedback

- Node 24.20.0 and exact pnpm 12.14.0; inherited dependency install completed.
- Microsoft C++ tools and SDK installed under .build-tools/vs2022; native addons load in Electron 43.8.6.
- Electron release SHA-256 checked against the official GitHub asset digest.
- Five inherited typecheck projects passed before the latest identity/MCP work.
- Main/preload/renderer production build passed; sandbox preload imports only electron.
- Actual hidden Electron launch: Porpita Dev 0.1.0, own userData, title Porpita, zero renderer errors.
  See evidence/20261108/native-shell-initial.*. This was a controlled profile with hooks disabled,
  no model invocation and no installation acceptance. Initial ORCA wordmark/promotion/notice issues
  found in that render were corrected in source; a new capture is still required.
- Real bundled Python 3.13.15 + PostgreSQL 18.6 + ACS wheel composition passed authenticated
  profile/projects/contacts/snapshot, identity consistency and unauthenticated 401 checks.
  Core and PostgreSQL stopped; test data retained. This is component evidence, not Native/installed acceptance.
- Windows pg_ctl inherited-pipe startup hang was reproduced and corrected using ignored stdio
  for the detached database start while keeping normal command output capture.
- Codex 0.166.0 login and OpenCode 1.4.6 credentials are available under the actual user account.

## Remaining work, in dependency order

1. Finish the communication cutover, including supervised-worker start/follow-up, remote/federation and
   all system notifications. Run scoped regressions and actual group/question/lifecycle scenarios.
2. Bind the existing snapshot/SSE/reducer, Human composer, history/search/read/draft/preferences/files
   and SourceLink to inherited UI primitives; preserve Host input, tools and approvals.
3. Finish existing-service, disconnect/reconnect, crash/reopen, remote and deliberate import behavior.
4. Complete source-relative portable-runtime recipes, branding/service/license audit, all desktop assets,
   native helper/daemon packaging, sealed Windows NSIS candidate and isolated installation.
5. Execute the 22 acceptance scenarios on that same candidate and complete the delivery manifest/report.

## Build and continuation

Use repository Git operations in D:/Chatgpt/Porpita with sandbox escalation for writes.
The app checkout is outside the initial writable roots; approved escalated operations have been used.
Original ACS repository remains the Git directory for ACS changes, never its management child.
Build: npm exec --yes --package pnpm@12.14.0 -- pnpm run build:win.
For focused iteration use node config/scripts/desktop-build/execution/run-electron-vite-build.mjs.
Always set ORCA_BACKGROUND_LAUNCH=1. Use Playwright CDP with hidden windows; do not steal focus.
Current build logs are under .build-tools; these and prepared runtime binaries are excluded from Git/asar.
Existing development scripts are under D:/Chatgpt/Agent-collaboration/.tmp/porpita-development.
install_communication.py copies owned staged files: keep its stage synchronized before rerunning it,
so it cannot overwrite later formatted/source fixes. Convert final build recipes into the client repository.
No external publication, production schema change or original Orca data import/overwrite is authorized.

## Latest empirical checkpoint — 2026-11-08, Native reception integration

- Actual hidden settings completed managed local setup and connected to its real service.
- Both Codex and OpenCode Native Chat views opened in the actual built application. Both actual
  session identities registered as distinct Core contacts with signed Receiver references.
- OpenCode's private account preparation completed through the actual settings button.
- First user prompt for real Codex→OpenCode→Codex acceptance was preserved in the Host queue:
  Codex rejected an injected enabled=false MCP table lacking a transport before model startup.
  Fixed by reading the selected Codex home's actual TOML and disabling only existing old servers.
  Three regression tests passed, the desktop rebuilt, and the same queued message is being resumed.
  The preserved native queue resumed after this fix. Actual Codex used porpita_acs profile,
  contacts, send_message and exact wait_for_response, but the first request exhausted its
  transport attempt budget against a stale receiver after restart.
- Restored all saved visible Host conversations/receivers at rest, including background tabs,
  through the actual Host restoration path. Main typecheck and desktop build passed.
  PORPITA-LIVE-02 reached signed prepare/readiness/dispatch and started actual OpenCode, but
  had no Native ACK: the Host operation ID lacked its mandatory timestamp/replay format.
  Fixed by deriving a stable Host ID from the verified original sealed admission's issued_at
  and Core operation hash. Two integrity/replay tests and main typecheck passed; the built
  app is being checked with a fresh explicit request. Old failed/uncertain messages are retained.
  PORPITA-LIVE-03 then passed with actual Codex and OpenCode Native Chat models:
  request message-6928c9d5fca44684810fdf8323b24bd6 received a real Host Native ACK, and
  reply message-d66fda0a271c4a5f8be0f11658c7a773 explicitly names that request in reply_to.
  Native input 1794141074618-adebfd96c8d48eff0154dc451f708858 was accepted in the original
  OpenCode journal under provider generation f84127af-f7db-4051-9a21-5d7e424eeab1.
  Core message state is delivered/runtime_acknowledged; the reply is delivered/target_inbox_committed.
  See evidence/20261108/real-native-live03.json and the two actual native screenshots.
  This is a development build on one Windows machine, not installed/remote/full-matrix qualification.
  Native harnesses also created .codegraph/.omo artifacts in the dedicated acceptance project;
  do not repeat a model's unverified statement that no files changed.
- New ACS increments (uncommitted, source tree main baseline preserved): dynamic endpoint registry
  refresh in communication maintenance; timezone-independent endpoint expiry comparison that retains
  legacy source digests/history. Seven real isolated PostgreSQL maintenance tests and three focused
  timezone tests passed. Other original ACS tracked edits remain untouched.
- Main and web typechecks passed after Harness preparation. Desktop production build and inherited
  sandbox preload verification passed. Native Host construction/recovery regression passed (1 test).
- The Core wheel contains the two listed runtime increments; its dependency manifest now records
  their source digests rather than describing it as an unmodified baseline.
- Current controlled profile: .build-tools/desktop-inspection-profile (initially hooks disabled).
  Acceptance project created through actual UI: C:/Users/D26FO/orca/projects/Porpita-Acceptance-20261108.
  This inherited default directory still needs product branding correction. No original Orca data was imported.
- No Windows installer has been built or installed. All 14 legacy A2A paths still require cutover;
  new RPC/MCP paths alone are not product acceptance. Remote/file/source-link and final 22 scenarios remain.

## 2026-11-09 — public CLI cutover checkpoint

- Reopened the existing isolated profile in a rebuilt hidden desktop. Real Codex used the actual
  Porpita CLI for `orchestration send`; actual OpenCode read it and used its own CLI for explicit reply.
  Send/reply/check each reported exit 0 in the native tool conversations. Core request
  message-420be9ba6dd248d1b46887654d924c44 is delivered/runtime_acknowledged; explicit reply
  message-b785a22852294ff3bbf0b563e84af96a names that request and is target_inbox_committed.
  Evidence: evidence/20261109/real-native-cli03.json plus both real Native screenshots.
- CLI classification now distinguishes ACS delivery facts from inherited worker follow-up receipts.
  A pending Native receipt no longer becomes a failed worker launch.
- Ordinary send/reply/check/inbox/group adapters use ACS. Question records keep Core references;
  their old message-table projections are handled metadata only, with no duplicated inbox body or wake.
  Pre-migration replies are refused and history requires explicit legacy selection.
- Original-key recovery checkpoints authority/actor/recipient/hash/handle in existing Host mutation
  receipts. An accepted target is read back, and uncertain writes retain the original key. No new outbox.
- Explicit worker_done/heartbeat notifications use Core, followed by the existing Host lifecycle rules.
  Host settlement and final mutation receipt share a SQLite transaction; no new old inbox row is written.
  Fifteen focused regressions passed, including real SQLite settlement rollback and author isolation;
  main typecheck and rebuilt CLI/desktop passed for this checkpoint.
- Subsequent source increments retire old pointer wake, route Host notices through the real Client,
  and intercept automated messages targeting other Agents. Their focused validation is in progress.
- This is development/reopen evidence on one Windows host. It does not qualify installation, remote,
  full group/question/workflow paths, fresh OS prerequisites or the final candidate.

## 2026-11-09 — Human surface, reopen and Native file checkpoint

- Added a collaboration dialog using the inherited titlebar, Dialog, Button, Input, Textarea and theme
  primitives. Contacts/workspace names come from real authorized Core data; no Root/Route console.
  The existing SDK snapshot/SSE/reducer owns its communication projection, separate from Native output.
- Actual Human UI→OpenCode→Human UI exchange passed. Request message-c3e13a83650246b09f18e7f18c8391b1
  was authored by the real project Client and reached Native ACK. Reply
  message-584fddaf3ac6405ca80714c2bbc53f8c explicitly names that request. See real-human-ui01.json.
- Normal quit/reopen retained Chinese/emoji draft PORPITA-DRAFT-REOPEN-01, the actual reply and correct
  Human author label. See reopened-surface.json and human-ui-reopened-chinese.png. This is development
  evidence, not installed-candidate acceptance. Project-scoped Client addresses are resolved from
  authorized conversations, independently of the global /profile principal address.
- Added complete body reads, paged message history/search, read state/preferences, CAS draft saves,
  real reserve/upload/finalize/download and explicit local reveal. Native file materialization reuses
  the original Host attachment store and its journal retention, never a sender's remote path.
- Added actual Agent-owned CLI `orchestration upload-file` and `orchestration send --attachment-refs`.
  Terminal send/inbox/upload now carry their actual attested Native source. Focused routing/author
  tests passed (21), file/caller entry tests passed (6), owner-label tests passed (2), and lost-observation
  Human inspection tests passed (9, including 6 previously covered cases). Main/web typechecks passed.
- Exact pending Human requests use existing Host receipts, authority/actor/hash/target/operation refs;
  inspection reads the original operation without resending or waking Native. The UI preserves the
  original key and waits for pending-request lookup before accepting a fresh send. Further installed
  interruption coverage is still required.
- Native attachment trial 01 revealed the Core default attachment hold; trial 02 revealed the remote
  sender guard. Both failures and their original receipts remain. New Core support is opt-in only for
  installed endpoints and the original signed Host attachment preparation. Generic Drivers/default
  Receiver paths remain denied. No database schema or ordinary Native input/output authority changed.
- Trial 03 reached a real Codex Native ACK, read the actual 139-byte Host file and independently returned
  challenge 0ca44a29d734f7dbbbaba668 and SHA-256
  bd9c7368e385cc6c9b7f49d04190252516335f5481745a9b748de289d47223c3. Native PNG observation correctly
  described the dark teal background, light teal central disk/ring and radial dots. Agent-owned CLI
  upload/send each exited 0. Its OpenCode relay message-73679303a5ed4980bf3f6c0d96350dd4 was blocked
  before Native input, so dual-Agent file acceptance is **not yet passed**.
- Exact signed preparation timing established 39.833 seconds of OpenCode cold preparation against a
  30-second sender budget. Host was then ready/idle; its same protected ensure completed in 2 ms.
  Managed budget is now 90 seconds; a prepare-only transport timeout defers the same original request,
  while changed-peer rejection remains definitive and dispatch uncertainty is never re-sent.
- Core signed/attachment regressions passed 58 cases. Portable Core/real isolated PostgreSQL passed
  12 cases including default holds, explicit Host queueing, active waits and maintenance. One prior
  maintenance run timed out while a desktop build competed; a quiet rerun passed without test changes.
  The Core wheel manifest lists seven exact source overlays on e5d71968; original unrelated ACS work
  remains untouched. No commits, push, public release or installer acceptance yet.
- Next: finish a real two-Agent file relay after the cold-start correction; complete all remaining
  A2A cutover (worker bootstrap/follow-up, groups/recovery, remote), Native SourceLink, existing-service
  trusted setup/import, source-relative runtime recipes, licenses/branding/service audit, full build,
  installer and the same-candidate 22-scenario acceptance.

## 2026-11-09 — real two-Agent file relay passed

- FILE04 passed after the cold-preparation correction. Human request
  message-75791affb7cd40f18f09fe9e0b449613 and Codex relay
  message-a9274541362a41318061a91d5459b654 each reached runtime_acknowledged.
  OpenCode reply message-db3bbf1fed1b4beeb7e6ccc75dd45335 explicitly names the relay;
  Codex report message-116bb013312e43e38e83cc0ebfe18105 explicitly names the Human request.
- Each actual Native agent read its own materialized 139-byte UTF-8/CRLF/emoji file. Both returned
  the fresh challenge and SHA-256 9ba345e22c206ab77ff623f369835c398e885be92e48d778967102095ab12f62.
  The challenge was absent from both request and relay message bodies. Independent physical-file
  hashes and exact Core reply relationships passed. Codex also observed the actual Native PNG.
- Evidence: evidence/20261109/real-native-file04.json and real-native-file04-verification.json.
  This qualifies this development flow on one Windows host only; installed/remote acceptance remains.
- Official Orca v1.4.253 resource archive SHA-256 passed; node-pty patch and Node pin match this
  source byte-for-byte. Added a source-relative locked native resource preparation recipe. It restores
  native dependencies only; product/server code and Windows launchers/addons are built from this tree.
- Next: complete the service/native package and Windows installer while finishing the remaining
  A2A paths, source links, existing-service trust, reproducible runtime recipes and same-candidate tests.

## 2026-11-09 — source navigation, terminal recovery and first installer

- Real Human message message-04609913107d4cc7a348f6c8322a78cf returned an original signed Native SourceLink.
  The normal collaboration View execution action opened the inherited Native conversation and positioned
  exact row orca:1794165664046-ffb3c62458cb506c926b61a015e20968 in the visible viewport (CSS top 312.58).
  See native-source01-target.json, native-source01-landed.json/.png. Source readers are composed from the
  actual authenticated Receiver and ExistingOrcaReceiverBackend signed ACK; Host checks the saved input,
  message, generation and epoch before opening. A provider name alone no longer identifies a Host instance.
  Prior Host-boot source availability still needs completion/verification; never substitute the latest session.
- The real terminal send entry initially failed before Core submission: optional attachment_refs was
  explicitly undefined. Actual SDK validation reproduced it; omission fixes it (9 focused tests pass).
  The failed request was retained, not sent under a replacement key. After normal app quit/reopen the
  actual Codex retried identical arguments with original request 56155192-b4cf-4d97-ba6c-9f3da6b07251.
  CLI exit 0 and mutation.replayed=true. Its one Core request message-40a1ca1d915c4487abe3b824e43ef97c
  reached runtime_acknowledged; OpenCode reply message-629daeb1cb6a4f4f87455bedbc0752de explicitly
  names it. Both real Native agents computed matching SHA-256 and OpenCode ran its native Git tool.
  Core acceptance, initial pending Native state and PTY accepted=false/zero bytes are separately retained.
  See real-terminal-source01.json and real-terminal-source01-verification.json. Development evidence only.
- Trusted terminal classification now precedes PTY receipt binding. Original PTY guards remain. Partial
  group sends keep the original audience and existing Host checkpoint; explicit retry only re-reads
  accepted targets and sends unresolved targets under their original keys. Real SQLite regression passes.
- Locked native resource recipe restored/verified 24 native files across nine target slots, including
  optional glibc 2.17. Node-pty patch and Node pin exactly match the fixed official archive inputs. All
  product/server JavaScript is built from this tree. Windows x64/ARM64 process readers, security addons
  and own CLI launchers were built; nine-target service template verification passed. Non-Windows and
  ARM64 execution are unmeasured. Additional MSVC ARM64 tools installed; original Rust default retained.
- Complete desktop/CLI/WSL/Web/mobile asset build passed, as did main/web typechecks. Source-location
  regression passed 3 cases. Native source reader imports pass under the actual embedded Python.
- First Windows NSIS installer exists (403859574 bytes, SHA-256 aa51bd33d6b572ba839411eb46b9b30eaa580295e40bf994077eb829d1b611fa),
  archived at dist/prototype-01. It is unsigned, not installed, and not a final candidate. Packaging needed
  stopping only the verified isolated-profile daemon that held a private DLL, then a project-local
  ELECTRON_BUILDER_CACHE to avoid the system cache's EXDEV rename. No unrelated process/data was changed.
- Closure inspection found PostgreSQL depended on a machine VC Runtime. Added a locked Microsoft
  VC143 x64 14.44.35112 app-local recipe (10 DLLs), original redistribution list, per-file hashes/PE checks,
  copies beside PostgreSQL and desktop packaging gates/extraFiles. Prototype 01 predates this and the
  optional-attachment fix. Rebuild before installed qualification; do not accept that prototype.
- Next: finish worker bootstrap/follow-up and remote A2A cutover, stable contact lineage/clear,
  existing-service trusted Native setup, import, source-relative Core/harness recipes and licenses/brand
  audit. Complete native dependency closure; rebuild/install and exercise a fresh normal profile with
  Node/Python/PG absent from PATH; finish all 22 scenarios against one final installation candidate.
  Product is NOT accepted; no final candidate installation, public release, commit or push yet.

## Worker instruction increment — verification in progress

- Task bootstrap and explicit task injection now call the normal ACS sender under the initiating caller. Initial task messages use deterministic Dispatch keys. Core references are nested in the original accepted Host receipt, preserving its Dispatch identity and preventing whole-start replay. Setup completion notices are authored by the Host Client through ACS.
- Main typecheck passed 18,325 files; nine focused receipt/contract/group cases passed. Desktop build passed. A real Native Worker/ask/reply/completion trial is running; this flow is not yet accepted.
- App-local Microsoft CRT now also accompanies both Harness executables; the official embedded Python runtimes are retained while missing CRT components are supplied. No final installer installation yet.

## 2026-11-09 — real optional workflow passed

- PORPITA-WORKFLOW-01 used real Codex and OpenCode on the existing Native Chat Host. A created one
  Run run_e54127c08ad1, Task task_00818488e574 and Dispatch ctx_194835bdb2b0 through worker-start;
  the first instruction message-d8f5aadead624b7692960a8c6e472ffd reached Native ACK through ACS.
  B used its CLI ask (message-f300190d160f4c14b829d135764ba1d1); A's CLI reply
  message-ea4a4871a7cc4aceb8775a275b55fe3c names it exactly. The Host question is answered.
- B wrote the actual 52-byte UTF-8/no-BOM/LF artifact, then submitted authorized worker_done through
  its own CLI/ACS identity (message-7399b31eefd840b3a9d2f2da87e92fc8). B separately replied to the
  instruction (message-09d10aa61a014e2a918a11d20e1e907f). A explicitly reported to the Human request.
  Independent public Host reads show Task/Dispatch completed and worker succeeded/settled, and Task
  result provenance is worker_report with the actual ACS completion handle. Physical bytes match
  SHA-256 c9eba189c6107df8f1b6f6101e47cff82d4af1c0c528c7ec2eeaccfa8be4ea31.
- Read-only inspection of that Run's old messages found no inbox body writes; only the permitted
  upper question reference projection remains. Evidence: real-worker-acs01-current.json,
  worker-acs01-host-state.json and real-worker-acs01-verification.json. This is development scope,
  not final-candidate/remote/physical multi-host qualification. Reused Native Chat path is measured;
  fresh worker creation and finished-worker follow-up still need practical checks.
- Experience findings: finding a Native Host address took multiple CLI queries, and the real task
  preamble still advertised orca-dev. Source defaults now emit porpita/porpita-dev, normalizing old
  command hints while preserving legacy input types. Main/CLI checks pass (18,325/4,181 files).
  Missing real macOS/Linux CLI resource filenames were corrected to match packaging configuration;
  scripts target only Porpita executable/install paths. Their actual OS execution is unmeasured.
- Windows private DLL closure static check passes 85 process/extension roots and 115 private
  binaries; installed machine VC Runtime is not counted as an OS dependency. This is static import
  inspection, not clean-OS execution. Actual final installer dependency validation remains required.
- Downloaded the exact existing 49 third-party dependencies as official CPython 3.13 Windows wheels,
  recording versions and whole-wheel hashes in config/scripts/porpita/python-wheels.lock.json.
  Running Runtime was untouched. Finish the source-relative runtime preparation recipe before delivery.

## 2026-11-09 — installed startup diagnosis and reproducible payload

- Prototype 02 installer (SHA-256 7dd2286d8f69cc9bfba65a04ad9c5b0a3ea976fbb84f408bd51d5b2b5d38cb37,
  407200112 bytes) installed successfully at C:/Users/D26FO/AppData/Local/Programs/Porpita. Product
  executable metadata is Porpita 0.1.0.0; Desktop and Start Menu shortcut targets/icons match it. The
  installed app-local CRT files match their locks. Original Orca data/processes were not replaced.
- Default installed startup failed before a window: same-directory hardlink and rename through logical
  C:/Users/D26FO/AppData/Roaming/Porpita returned EXDEV. Independent Node/Python probes reproduced it.
  Native final-path resolution shows that selected profile redirects into D:/WpSystem/.../OpenAI.Codex.../
  LocalCache/Roaming/Porpita in this launch environment. Operations through that same physical directory
  pass. Do not treat the failed launch as product acceptance or bypass the atomic admission rules.
- New startup code canonicalizes the selected Windows profile through realpathSync.native before
  admission. It keeps the same directory/data and honors explicit --user-data-dir. Existing E2E escape
  refusal is preserved. 27 focused existing/new startup tests pass; main/web checks pass 18,328/15,485
  files. Prototype 03 with this correction is rebuilding; its installed first-run result is still pending.
- The first package retry correctly refused a missing Web manifest after renderer regeneration. Web
  projection has been rebuilt and full packaging checks retained. Do not use the incomplete unpacked
  intermediate output as an accepted installer.
- Entire private Runtime now rebuilds from source-relative locks with one developer command:
  python config/scripts/porpita/prepare-private-runtime.py --acs-source <checkout> --install.
  The isolated Core wheel is 6f5a658f4c1269dea79e6b5a0d50baf90a79e14bf8e094c6fe44702910ef7028;
  immutable baseline archive excludes unrelated pre-existing source edits, retaining all seven approved
  overlays. 49 official dependency wheels plus Core assemble 4532 library files. Only two developer
  PyWin32 postinstall/test scripts are outside the embedded-library payload. Harness and source license
  hashes pass; PostgreSQL server/third-party licenses are included. New staging imports and PG --version
  pass; DLL normal-import closure passes 85 roots/115 private binaries. Previous generated payload is
  backed up, application user data is untouched. See docs/porpita/BUILD.md.
- No installed workbench/Core onboarding acceptance yet. Final product remains NOT accepted; all
  remaining implementation and same-candidate 22-scenario work continues.

## 2026-11-09 — installed workbench, identity isolation and continuity increment

- Prototype 03 (SHA-256 7d0f1b75fe51694a641f4e0e48371b2c57dd87646168b82033364d542a9c02e7,
  406815995 bytes) installed/upgraded with exit 0. Canonical profile startup passed. Normal onboarding
  started the installed bundled Python/PostgreSQL Core 2.3.1 and prepared private OpenCode authentication.
  The real UI created C:/Users/D26FO/porpita/projects/Porpita-Installed-Acceptance-20261109.
- Installed Codex and OpenCode independently used native terminal tools and their actual Porpita ACS
  MCP credentials. Codex identity agent-a56a3f3aca59ccb92acf20a4157c2a44 and OpenCode identity
  agent-b81ba3554e9bb35d6836910b6d955ad0 share project porpita-0d267b376a9bcee2fe74d0f82dea1508.
  This was a read-only smoke, not the required installed A/B development exchange.
- OpenCode also inherited a pre-existing administrator ACS MCP configuration. Candidate 03 is rejected
  for that isolation defect. Source now disables inherited ACS transports in the process overlay while
  preserving unrelated native/provider/MCP settings. Actual bundled OpenCode 1.18.31 configuration
  parsing verifies the transports disabled, 12 other MCP configurations retained and original config
  hashes unchanged. Nine focused source/config cases pass. Re-test real model tools after installing 04.
- Disconnect now stops this application's owned local Core/PG, blocks its Host bridge and invalidates
  current Native bindings. Reconnect restores saved Host receivers. Same-boot receiver enrollment resumes
  original keys, TLS certificate, endpoint and ledger rather than attempting O_EXCL replacement.
- Native source references now distinguish Host boots. Retained signed Receiver source readers restore
  at startup with no permission to prepare/launch a Native child or rebind today's Slot. Historical UI
  still requires Core ACL, the exact original source, saved record and accepted original Host input.
- Actual resolved Native launches capture binary/configuration digests without retaining environment or
  credentials. The advertised NativeLink proof port reads the already-ready Host child and requires the
  exact spawn token/fence and locked executable digest. It does not launch or grant Native controls.
  NativeLink limits/storage are now adopted by first setup. Existing private feature-1 databases require
  explicit Start local service; that action makes a real pg_dump backup before adoption. Ordinary launch
  verifies and reports preparation required. This is private Porpita data only, not production adoption.
- A loopback-only existing-service Host extension now authenticates the trusted Client and issues each
  Agent its own credential. It never passes the Client key to the model. Normal Agent keys get 401 on
  identity/Receiver management. Host callbacks and caches are fixed to service authority/incarnation,
  mode, endpoint and current key; same-boot transport refresh preserves immutable Receiver identity.
- Real isolated embedded Python/PG/Core checks, with node/python/postgres absent from the child PATH,
  pass two Core restarts, same-boot original key retention, distinct next-boot endpoints, retained readers,
  adopted NativeLink reads, trusted Client enrollment and Agent management denial. These are component
  checks with scripted registration, not real Native/remote/model acceptance. Actual installed main had
  hydrated node/python on PATH; do not claim it was a clean OS/no-development-tools installation.
- Full desktop build/typechecks passed before the final existing-service increment; latest main check
  passes 18,333 files. Full desktop/template regeneration for candidate 04 is running. Prototype 03 was
  normally quit; only its verified own idle terminal daemon 54456 was stopped for upgrade. User data,
  original Orca, original credentials/configuration and unrelated processes were retained.
- Current /clear implementation keeps its session ID and therefore current Slot. Real clear/reopen/source
  and busy-queue evidence remain pending. Existing-service real two-Host execution (including the inherited
  remote-workspace path), federation cutover/lifecycle references, explicit old-history import and final
  branding/service sweep remain incomplete. Do not mark WP07 or final acceptance complete.
- Product is NOT accepted. Finish implementation and all 22 scenarios against one final candidate;
  finish user runbook/manifest, source commits and artifact delivery. No public release/push was made.

## 2026-11-09 — installed candidate 04 and actual restart regressions

- Candidate 04: 406820889 bytes, SHA-256 d2b2e4e5cfbaf9be5ae8ec37a4180c5568e983017ea74ec474e41e0d0022fa08,
  NotSigned, installed/upgraded exit 0. Installed ASAR matched 01c716aae350504d6e6090eaf1e9d1231222bab3fe05bb974b5a8519239e65e6.
  Full desktop/typecheck, nine-target orcad and NSIS gates passed. Native CLI 0.1.0 ran with only Windows
  directories on PATH; installed porpita.cmd is present. This candidate predates the disconnected-mode
  legacy-ACS suppression, exact transcript landing, draft revision and cold signed-source fixes.
- After upgrade, automatic startup correctly reported private service preparation required. Clicking the
  real Settings action under a controlled Main PATH (where node/python/postgres each exit 1, Git exit 0)
  made a real 290578-byte PGDMP backup and adopted private features=2. Installed embedded Python/PG
  were the running executables. Core 2.3.1 and original authority/installation incarnation stayed intact;
  NativeLink limits 1024 and storage are advertised, live NativeLink write qualification still pending.
  This is a real installed controlled-PATH test, not a clean Windows OS or new user account.
- Actual installed Codex used Native tools to create the QA project's 217-byte UTF-8/no-BOM
  porpita-label.ps1 and exercised seven PowerShell cases. Its one ACS request message-bf8ad15fbf5745d0a077a28a319e57aa
  woke OpenCode after /clear. Native ACK binds input 1794180739071-ee50d36a2b78f8a34ea4f72ed26011fe,
  session opencode_1800aadb_f32d_4d4a_9427_c96b9d0d26d8, generation 997a4ab0-c007-4b8d-9777-f16b2cdb96fb.
  OpenCode used its same Agent slot b81ba3554e9bb35d6836910b6d955ad0 and only porpita_acs to independently
  pass seven real tests and explicitly reply message-fa740a3e61654c0a9a4a0ec5542b3ccf to that original.
  Five independent PowerShell cases and both models agree on SHA-256
  55beeeecebf37fcdfcdca7ab7bf29b78f0d0ae171c3bb09f4f0203861e9687fb. Initial wait 120s timed out;
  A resumed via a user prompt naming the same original handle, read the late actual reply and continued
  native verification. No request was replayed or replaced, and no human forwarded the reply body.
- Own Human composer request message-aaa6fd0dec17436abca7b6683100b865 reached actual Native ACK.
  Client read of unrelated private A/B message correctly denied. The own request's original source is
  input 1794181258188-d63f0ab7781b4a21f055f97d7278d9cf, same OpenCode session/generation as above;
  original Host boot b71b06bd-3ff8-4fbc-b9a1-f0f90c65798a. Its UI opened the correct tab but left the
  actual row below the viewport (top 1139.42/950). Fixed the loaded input lookup to use exact transcript
  slot instead of the sampled rail. Rendered regression fails before, all seven navigation cases pass
  after. Verify installed landing again after rebuilding. Human-request model reply itself not measured.
- After sending, reopening the same contact reused an old draft revision; switching contacts forced
  an actual fresh read and preserved multiline Chinese/Japanese/emoji draft revision 3. Source now
  propagates committed draft revisions to the parent and re-reads on open. Status inspection no longer
  replaces a current saved local HTTP client while starting the same Core, and Native binding waits for
  actual connected authority. All related typechecks passed. Retest installed dialogs on next candidate.
- Actual Settings Disconnect stopped the owned service; Reconnect retained authority, original source
  and revision-3 draft in the same Host boot. Normal quit and reopen installed Main 54036 -> 52744
  retained profile, both slots, draft visible in composer, three scoped Core messages and two Native ACKs,
  with no new message/admission. Historical source was unavailable on the new Host boot: real log shows
  resolve_original called the retired Host's current ownership during Native source read. Registry and
  original metadata had restored correctly. Fixed Core to reconstruct an already ACKed source from its
  original signed prepare/dispatch, without any live-owner or reconcile callback. Existing uncertain
  operation reconciliation remains unchanged. Four focused cases pass; broader escalated TLS suite
  running. Previous restricted TLS attempt was stopped only after verifying its exact two owned PIDs.
- Rebuilt/promoted locked generated runtime with Core wheel SHA-256 b9be2c0a434c71ff301787cb739412f7c0b95020888364b43a2a92738be54760. Installed candidate 04 still
  uses its original bytes; no hot patch to installed data. Cold-source fix needs next candidate and actual
  same-input proof. Candidate 04 current hidden Main 52744, interactive helper session 29771. Actual
  installed CLI serve is starting an isolated second Host in that helper; readiness/pairing not yet
  verified. Keep pairing offers and credentials in memory only. Continue physical-same-machine two-Host
  test, then federation cutover and explicit import, all remaining real functional scenarios.
- Product is NOT accepted. Source edits uncommitted; ACS main baseline and unrelated pre-existing work
  preserved. No public release, push or production adoption. Finish same-final-candidate 22 checks.

## 2026-11-09 — two real installed Hosts, extended-path fixes and candidate 05

- Actual installed CLI started a second hidden Electron Host under the independent profile
  D:/Chatgpt/Porpita/.build-tools/installed04-second-host-35zMA2. Its Main PID 14304 and runtime
  b960a44a-acbd-49d7-b3ff-4ef6187d51be listened on loopback 51781. Same physical Windows x64 machine.
  Paired via the real verify-and-add port with explicit local-lab loopback intent, environment
  3742a92b-6600-4a4a-966a-303a0d7f5fe3. No pairing code or access URL retained in artifacts.
- Second Host connected to the real first Host ACS in existing-service mode as trusted Client and
  prepared its own bundled OpenCode account. Real paired repo.create made a Git project at
  D:/Chatgpt/Porpita/.build-tools/installed04-remote-projects-7KJ2c8/Porpita-Remote-04,
  repo 756ad76b-99eb-4377-932a-50056593f2ab. A test AGENTS project block points at the same authorized
  namespace. Actual inherited desktop workspace selection/New Tab opened remote OpenCode Chat.
  Agent slot agent-7234becd5c95cf296951865bdafad9de was automatically registered before any prompt,
  Native session opencode_02ebcf5d_53a5_4b10_bca8_117ddd1d9601, host porpita-host-7f6be78ea79fbaff298592bc319ae468.
- Real installed Native Codex sent one ACS invoke, message-b672f725a3da4bb3980b9064b34bf7fa. Its immutable
  dispatch selected second Host endpoint porpita-receiver-596d1df453114691f4941cab025c47a6,
  attempt delivery-attempt-4fd9dc8e-9f03-4328-89ab-0c16db045448, and original Native input
  1794184748956-e961d3dba94d40d126b11f21dff06266 reached ACK. Remote OpenCode used native shell/Git
  in its real work directory and sent exact explicit reply message-30f56f3f5e174bce85f8e7f6b6ab8b76.
  Both agents and independent verification agree on challenge SHA-256
  a98b74d228ae00bdf66c288cf8086719a8d3eb954f810ee5ece7799c6013d22a; A observed the real reply.
  Evidence installed04-remote-text-verification.json and installed04-remote-modelA.txt.
  This qualifies ordinary two-process remote Native text on prototype 04, not cross-host attachments,
  physical networking, remote optional workflow, or same-final-candidate UX21.
- Real existing-service disconnect/reconnect on the second Host left the first Host's Core running.
  Native remote workspace sleep stopped the original OpenCode session without retiring the tab.
  Only verified second Host Main 14304/daemon 41504 were stopped. Primary Main 52744 was normally quit.
  All profile data, paired identity, workspace and source journal data were retained. No installed
  Porpita processes remained at the final probe. Prior interactive session 29771 is no longer for control.
- Installed file UI stopped before send with attachment_content_unavailable. Exact bundled Python
  probe reproduced FileNotFoundError on Windows CAS staging below a 222-character Scope root.
  Existing WindowsArtifactStore now uses explicit extended Win32 I/O paths while retaining the same
  scope, bytes, hardlink/digest checks and relative references. 67 Windows CAS/content cases passed.
  Actual embedded Python using the source fix wrote/read an actual 290-character path; the rebuilt
  bundled Runtime completed real HTTP reserve/upload/finalize/download on an isolated 290-character
  path with identical 52 bytes, ready result. Initial evidence glob itself needed the extended prefix;
  no product HTTP error after the fix. Retest UI plus both Native hosts from candidate 05.
- Actual live second Host /proof responded. Original installed NativeLink write failed because owned
  endpoint expires_at is nullable and storage tried to parse it despite owner mode not applying shared
  lease deadlines. Source now checks shared deadlines only, without relaxing exact binding/current
  proof. Same original request with actual live proof through installed Python + patched source committed
  revision 1; read back through installed Core's normal HTTP metadata route. Seven real isolated PG
  NativeLink cases passed, including owner null lease and expiry/current binding refusal. Candidate 05
  contains the fix; no installed app byte hot patch. Thirty broader Receiver/TLS original-source cases pass.
- Actual child spawn now pins its provisioned ACS scope. Input ownership and attested CLI cannot
  adopt a different service/actor credential while the existing provider still has its old launch
  environment. Main typecheck passed. Earlier unconnected-mode suppression verifies actual bundled
  Codex parser disables legacy ACS and preserves 10 other MCP entries and original config bytes.
- Final candidate-05 Core wheel SHA-256 03710d29736dd5489900acae3c03a82b1f0eaf5c23ba7a9077efd8975efe4845,
  nine locked source overlays. Desktop/typecheck, native template build passed. NSIS package is
  running under unified exec session 75405; log .build-tools/package-windows-prototype05.log. Candidate
  04 is archived under dist/prototype-04. After package exit 0, hash/inspect actual signature and ASAR,
  then install from dist. Helper inspect_installed05_interactive.cjs is prepared for normal profile.
  Restart second Host through start_installed04_second_host.cjs start({reopen:true,candidate:'prototype-05'}):
  same retained profile and port 51781, new live runtimeId, existing pairing should reconnect. Before
  constructing any new Host/Agent, check retained state. Retest exact old own-message source and visible
  landing, draft update/reopen, then real cross-host attached file. Do not replay the failed prototype-04
  upload as a message; it never sent. Use fresh fixture and observed same Agent slot on candidate 05.
- User runbook now has actual installation, collaboration and data instructions. WP07/09 still open:
  reachable legacy remote optional task path (send-methods -> send-remote, federation.ts terminal-only
  task preamble and old federation-relay body imports) must be replaced; independent import remains
  unimplemented. Actual local and ordinary remote A2A are measured. Use createStructuredWorkerSession
  and existing attachment/dispatch bookkeeping for remote task cutover; body should be ACS, relay
  only exact workflow references. No full new task system or stale/pending Native replay.
- Other outstanding: full installed file flow, busy/queue, actual approval, worktree/editor/browser,
  fresh Worker/follow-up, group/Gate, history/prefs/IME, final brand/service/permission sweep, actual
  uninstall and source commits/manifests, all 22 on one final candidate. No final acceptance or public release.

## Prototype 05 installed evidence and Prototype 06 cutover (2026-11-09)

- Installed 05 (NotSigned, SHA-256 0a80ba6b117ac246d21e8184f35e62983d6d4865fb6e87e589de6e6a1fe4b375) recovered the old signed source location and draft through a cold start. See installed05-historical-source-and-draft.json and its cropped transcript screenshot.
- Installed 05 delivered a 90-byte text attachment via real Codex, a second Host and real OpenCode. Both Native ACKs refer to the original messages, and target bytes match independently. See installed05-remote-file-verification.json. The two Hosts used independent profiles on one Windows x64 machine.
- Installed 05 created a real Git worktree, saved a file in Monaco, opened its Diff, ran a terminal command that wrote a proof file, split two terminal panes, and loaded the fixture HTML in the embedded browser. See installed05-native-workbench.json.
- Current source adds explicit local Orca message archive import, and a separate profile import for settings/workspaces and readable Native history. Imported Native records retain historical identity but cannot reserve a process or replay a receipt. Existing profile and source files are preserved. The six focused tests in four files passed (test-acs-federation-profile-final.log).
- Paired worker attachment now negotiates the Porpita ACS capability, verifies one authority/incarnation/project, prepares an actual Native worker, and lets the initiating coordinator send the brief through its own ACS identity. Exact ask/reply, control, and report contents use ACS. Only typed workflow references and explicit lifecycle facts cross the paired Host control channel. The old pending body relay is retained as archived data. The focused SQLite test proved repeated original report reference settlement and no duplicate mailbox row. Actual installed paired worker start and settlement are still to be exercised.
- ACS delivery source is local commit 4f750ec173a0422a56b9989a43acf973cbc980d9 on codex/porpita-acs-runtime, isolated at D:\Chatgpt\Agent-collaboration\.tmp\porpita-acs-source-20261109. The original main checkout, uncommitted docs and other files were preserved. Nine source overlays for wheel 03710d29736dd5489900acae3c03a82b1f0eaf5c23ba7a9077efd8975efe4845 are equivalent after line-ending normalization. No push.
- Prototype 06 build: desktop and orcad template completed, NSIS packaging running (exec session 34311). 05 is archived in dist/prototype-05. No candidate is PRODUCT_ACCEPTED until all required scenarios are observed on a single installer.


### Installed 06 and unpacked 07 follow-through

- 06 installer SHA-256 724814b5d8a3e2ae5b2a0e1eb83e059670b9404dbc0b75f456f621527059a495 (406841930 bytes, NotSigned). NSIS /S exit 0, installed app.asar e1872803622c8b8bad5d678ca3e68a401e0d3c43305891c04eee9d4abb6abe2e, byte-identical to the verified bundle. See installer-prototype06.json. New current ACS wheel rebuild from clean 4f750ec reproduced the identical wheel digest.
- Actual 06 launch from the retained profile and the retained second Host succeeded without pairing again. The second runtime b6525d94-2485-4165-a30a-e728812c451f advertised orchestration.federation-acs.v1. Actual virgin profile D:\Chatgpt\Porpita\.build-tools\installed06-fresh-cC2Mhb launched using the explicit --user-data-dir switch; original onboarding Integrations > Start local service established a separate managed Core 2.3.1, authority porpita-e20220d4802413c25f43e9624f5526ab / installation-1. Windows PATH still contained developer Node and Python on this test; no claim of a developer-tool-free first boot from this run. Both profiles were closed normally, second Host was parked then stopped (exact 16604/36708 lineage), port 51781 free.
- 06 actual Codex in the local QA workspace attempted one remote worker-start. Home Task task_23303f5110f8 / Dispatch ctx_f20fc2b1502a failed schema admission at remote_attach. Remote DB has zero matching attachments and no Native effect. The login Actor.address is a principal reference; it is not a collaborator delivery address. Source now takes the actual registered Native address and verifies the authenticated Agent slot and project first. No replay of the rejected Dispatch. Evidence installed06-paired-worker-address-refusal.json.
- New handshake compiles (18,341 files). A separate unpacked 07 QA build (exec session 95542, logs build-desktop-unpacked07.log, build-orcad-unpacked07.log, package-unpacked07.log) is being produced under dist/win-unpacked. The latest installed candidate remains 06. Use inspect_unpacked07_interactive.cjs and start_unpacked07_second_host.cjs from the ACS .tmp/porpita-development directory; retain the original primary and second Host data. Submit a single new Native request with unpacked07-paired-worker-prompt.txt; verify no effects for the old 06 Dispatch. Exact UI navigation: close any modal "在任意窗格中听写" via its scoped Close button; click [data-worktree-id^="c364d6d1-72fc-4623-917a-cf7aca45a8ea::"]:visible; click [data-tab-id="structured-agent-session-codex_57e963dd_75e3_4bdf_990a_14b427edfc53"]:visible; use the original composer. Scope snapshots to Native Chat or the QA dialog; avoid enumerating the home file tree.
- The inherited federation regression run had 101 failures / 36 passes, principally because old harnesses expect terminal attach and body relay. The new sync tests retain cursor, duplicate and generation checks and assert archived body packets stay untouched; their first port passed 12/13, final rerun 43702. The new contact regression tests are under 29902. Automatic approval review rejected a proposed output/auto-release test rewrite that would replace Worker start with seeded rows; it was not applied. Keep existing tests and cover real Native start, then update relevant regression checks preserving actual launch/settlement boundaries. Do not bypass the rejection.
- Remaining acceptance: real repaired paired Worker on the unpacked bundle then a final installer; full same-candidate 22 scenarios, outstanding approval/queue/group/history/image/import and uninstall qualification. The source handoff now includes MESSAGE_PATHS.md and BRAND_AND_SERVICES.md. No final product acceptance, no public deployment.


### Unpacked 07 actual Native Worker and installed import

- Unpacked Windows app 07 passed the same desktop/CLI/template packaging gates (session 95542 exit 0). It is a QA build, not an installer. Main PID 7980, interactive exec session 9163, inspector inspect_unpacked07_interactive.cjs. The original second Host profile reopened at port 51781, runtime b01575f3-6d35-450e-ac50-ab3cb98ad946, CLI PID 10204. Both use the retained Core authority and pairing. Do not launch another copy of either owned profile.
- Real Codex submitted new 07 once. Home Task task_25db3576dde8, Run run_051de675d0c3, Dispatch ctx_1729f7944f07. Actual far Host prepared OpenCode Native worker session a70da440-6a85-40af-a826-38ff13b7de9a; structured handle structworker_b0a0a793-e4a6-41b0-adcf-32e417c41be3; ACS slot agent-3efcf52f5fffdf348f94cdb535ceefee. Home's original instruction message-4339691b45784859ae5e7dbfc4c3714d / op-201467bc-7b07-4c3e-9077-32b88efa0b74 reached nativeState accepted, stage input_accepted. Actual federationReadOutput returned provider opencode, liveness live, and native shell tool executions in the exact remote QA worktree. No effect on rejected 06 Dispatch.
- Two more real defects found: worker-show replaced Home effects with remote observation and erased the recorded ACS target/receipt; and Windows ask refused the new CLI name (only orca/orca-ide in enum). Both fixed in source after 07, not hotpatched. Home keeps original ACS target and instruction, and a remote contact-ready observation alone cannot mark a Home instruction accepted. CLI AskParams accepts porpita. Focused tests passed: contact 2, cursor/replay+malformed receipt 13, evidence retention 1, public workflow/ask 3. New desktop asset build session 33549, log build-desktop-next.log. Run appropriate validations when complete; output bundle currently running from dist/win-unpacked must not be overwritten until parked/closed.
- One user continuation PORPITA-PAIRED-CONTINUE-07 was submitted in the original A Native Chat while A was working, requesting an actual direct ACS question and reply in the same Dispatch because old Windows ask failed before effects. No replacement Worker. The live task is still open at this checkpoint; monitor with read_unpacked07_worker.cjs in session 9163. Preserve original operation identities. Only close after any needed exact effects have resolved. Final same-candidate Windows ask and worker_done acceptance still required.
- Actual installed 06 disposable profile imported a real user-selected test fixture Orca configuration and message DB via Settings. UI reported one workspace and one read-only message. Independent checks: original config and SQLite hashes unchanged, a separate profile exists and active profile unchanged, archived original id/author/body remain exact. Evidence installed06-profile-and-history-import.json. Native index read-only isolation separately passed actual SQLite fixture tests. Installed06 isolated test app (9262) normally closed after import.
- Full inherited federation suite has many old contract expectations; new focused tests passed but broad regression is not reconciled. Do not bypass automatic review rejection on replacing start with seeded old resources. Keep existing launch tests and actual Native proof. No product acceptance. Windows installer 06 is still the only latest installed artifact; do not count 07 as installer acceptance.


- User requested disk housekeeping. Removed five obsolete installer archives (01–05, 1.89 GiB) and seven explicitly verified generated runtime/source staging trees (4.66 GiB). Drive D increased from 35.65 GiB to 42.29 GiB free. Kept installed candidate 06 and its current installer, active unpacked 07, current runtime, pinned wheel, all profiles and evidence. Build recipe now uses a scoped temporary ACS source directory and verified the same wheel digest, with empty generated staging after the build. Reuse package output and retain at most one predecessor until replacement is verified.


### Unpacked 07 completion, installed 08, and active 09 build

- 07 original Worker actually read the exact ACS reply with its own OpenCode identity, wrote the expected 38-byte paired-worker-07.txt (SHA-256 40146c15afa84526930bd0974817bc8c7b7bdacda6aa286baeb8e39a0ff40bbc), and issued one genuine worker_done. Home Task task_25db3576dde8 / Dispatch ctx_1729f7944f07 settled completed; paired attachment succeeded. One reference-only relay (no body), sequence 1 acknowledged. Core question message-da089720e4e347828070f88710377417, actual A reply message-66eda58fd6b1489894ff0bcf0a496f79, Worker report message-308b52f0dffb4707be3addb2ea38a45e. Evidence unpacked07-paired-worker-completion.json and unpacked07-paired-worker-exchange.json. The answer was read by the actual B model; the test operator supplied only the original reply handle through the existing native composer because A chose message_only. Do not claim automatic Native receipt of that reply or 07 installer qualification. Both 07 workspaces slept cleanly and both apps stopped.
- 08 installer 406841411 bytes, SHA-256 91a4faf76c203d1f4e7a27447e479c7b6590ca786a5a8d4f75175b5c0288d8bc, NotSigned, install /S exit 0, actual app.asar 694e18f973653a10adb3a894e97ade7295f8616febf196b247ea06190d35c451 matches. Installer 06 was removed after replacement verification as requested; keep actual evidence. 08 exact packaged staged source tree 793ca206ce17d0da4dded81213e045b9672c88ff reproduced from the upstream Git commit via docs/porpita/evidence/20261109/porpita-source-candidate08.patch, SHA-256 d6902b82d00b9d729550cf4a5416bd9e99ab49d205c9b0d376b2fec693cefcf1. No client commit yet, no push.
- Source pre-commit with pinned pnpm ran and failed on actual lint checks. Applied safe autofixes scoped to 85 owned changed source files and fixed collaboration UUID generation with the existing non-secure-context utility. Other targeted imports/control flow fixes applied; no lint ignoring or generated contract/module rewrite. Auto-review rejected the combined action to delete the dead prompt field and ignore the generated ACS files, then rejected a proposed generated schema/module repartition. Neither rejected change was applied. Use the exact tested source patch route permitted by the development package; keep existing validation and preserve generated schema identity. There is no user approval pending. Do not bypass auto-review. Rebuild after any semantic source fixes.
- Active installed 08: retained main app PID 55988, interactive session 85839; retained second Host CLI PID 39564, runtime 0054aedb-18d2-4aab-8947-33f182ba2619, port 51781; fresh main PID 55812, interactive session 75694, data root D:\Chatgpt\Porpita\.build-tools\installed08-fresh-o72c0o. No real 08 remote Task was submitted: helper correctly stopped at managed-local needs-attention. Original preserved paired identity, no re-pair.
- Actual 08 fresh onboarding with scoped real Windows/Git PATH (where node/python/postgres false, git true) started bundled ACS 2.3.1 in a new independent authority. Evidence installed08-fresh-managed-setup.json. Retained profile failed two normal attempts with local_core_start_timed_out. Original PG started and fast-shutdown completed. Actual 22 retained source files; each restored reader took roughly 2–3 seconds, only first 9 files touched before timeout. Root: resources/porpita-core local_app() synchronously restored all historical Native readers before opening authenticated HTTP. Fixed source to restore in supervised lifespan background after service readiness; retained restoration never overwrites a live transport and does not rewrite old source metadata. Shutdown waits for the scoped restore worker to finish the current item. No data reset or profile edits. Actual retained cold startup must be verified in 09 and exact old source after background completion.
- 09 full build and NSIS packaging in exec session 44629. Logs build-desktop-prototype09.log, build-orcad-prototype09.log, package-windows-prototype09.log. Reuses dist/win-unpacked and temporarily moves only installer 08 to dist/previous-08 when packaging starts. 08 apps continue while building; close only the known QA profiles (and any exact child PTY daemons) before 09 install. After 09 actual installer exit 0 and ASAR match, remove 08 predecessor archive per user disk guidance, keep only useful small evidence and necessary source patch.
- Immediate next work: capture original 22 source metadata file hashes before upgrade; inspect 09 build and latest typecheck; on installed 09 verify both fresh managed and original retained re-open with old messages/receiver evidence. Then run the direct CLI paired Worker flow (template .tmp/porpita-development/installed08-paired-worker-prompt.txt, use new marker and unique output name for 09), actual local A/B and remaining 22 acceptance on one installer. Helpers inspect_installed08_*.cjs / installed08-fresh-setup.cjs can be copied to 09 with exact labels. No product acceptance yet.

