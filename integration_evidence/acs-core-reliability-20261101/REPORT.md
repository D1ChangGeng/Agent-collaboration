# Core input and uncertain-ACK follow-up

This slice compares development-package v2.33 requirements R09/R15/R21–R23/
R26/R32/R34 against source based on `018ed5b5b819c9ef084f1c8f946ad2ccdc1b9081`.
The product patch is v2.0.2. Tests use an isolated Authority/schema and
independent Windows Codex / WSL OpenCode contexts; production state is not
used to manufacture the evidence.

## Changes and actual defects

`runtime/mcp_runtime.py` measured JSON after ASCII escaping. A legal 32 KiB
UTF-8 emoji message could exceed that separate 64 KiB measurement and fail
before the declared message-content boundary. Input JSON now uses UTF-8
without ASCII escaping for its byte limit. Boundary Chinese/emoji messages
are submitted and read back unchanged; oversized content still fails.

The same entry now names missing required arguments, JSON types, enum choices
and declared bounds through the existing `field`/`guidance` error fields.
`runtime/communication.py` identifies invalid `content`. No supplied values
are echoed. Guidance is limited to callers allowed to discover the tool;
hidden tools and invalid credentials remain denied, and backend errors remain
redacted. These are additive result details, with no new runtime task entity
or result-schema version.

The PostgreSQL cases prove failed sends create no message, a corrected send
does, the original content is retained, exact UTF-8 boundaries work, malformed
types/ranges are rejected and unauthorized callers do not obtain guidance.

## Real models, lost ACKs and a new sender context

The ordinary test Receiver closes its actual TLS connections after committing
the dispatch result and readback results. The controlled network fault is
explicit; the signed Receiver service, Native adapter, model and ordinary B
MCP reply path remain real. This source-entry test does not qualify a new
installed-console or physical-host profile.

A1 uses normal ACS send with invoke + async, retains its actual returned
message handle, performs an immediate observation and ends its client turn.
A2 is a fresh real Codex context with the same authenticated communication
identity. It receives only that original handle, never B's answer. It calls
`wait_for_response` and `read_message` without sending again. B independently
uses its own ACS MCP to send the explicit related reply.

The final case passed. Core delivery remains `uncertain`, with high-water
`runtime_dispatched` and one attempt. Receiver evidence identifies both lost
ACK purposes. A2's actual wait returned `satisfied`, and the retained B reply
had the expected author and relationship. The final Authority contains two
communication messages, one reply relation and no `work_items` table.
Exactly one `POST .../prompt_async` occurred. No terminal collector/event
subscription or evaluator dispatch was used. Model elapsed time for this
bounded case was about 74.5 seconds, not a latency SLA.

Earlier attempts are not counted as passing this case: missing test environment
configuration and a cleared `/tmp` interpreter stopped bootstrap; a fault
switch was initially not retained across configure/start, so the explicit
fault assertion rejected an otherwise normal real exchange. A later attempt
lost ACKs but its first caller's 120-second observation returned without a
reply. The replacement-context case then proved continuation without resend.
Raw logs and model output remain private; only bounded aggregate facts are
published here.

## Verification

- New input/UTF-8 PostgreSQL cases: 12 passed, including unavailable guidance
  discovery being reported as a service failure rather than permission denial.
- Related communication/content/configuration/interruption PostgreSQL cases:
  51 passed, 3 opt-in/environment skips.
- Current local default Runtime component run: 215 passed, 1,429 skipped.
  Those skips are not database/model acceptance and are not counted as passes.
- Independent real-model ACK-loss/replacement-context case: 1 passed.
- Windows installation/release tooling: 257 run, 220 passed, 37 platform skips.
- Skill validation, focused Ruff and whitespace checks passed.

The new PostgreSQL file is included in the explicit CI database step. The
real-model test remains opt-in and requires approved credentials and a real
Harness; its default skip is not acceptance. Package/source integrity is
bound to the per-file source manifest recorded by the actual test.

## Scope retained

This slice adds input fixes and the stated uncertain-ACK/new-context evidence.
It does not claim every real Harness fault window, Shared/restricted Native
profile, opposite physical Native direction or sustained-load SLA. The earlier
user-requested exclusion of a 1302-1 whole-host reboot remains in effect.
No production cleanup, credential export, task lifecycle, terminal-result
projection or automatic Git synchronization is introduced.
