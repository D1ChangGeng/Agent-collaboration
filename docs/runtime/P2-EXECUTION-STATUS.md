# P2 execution status and evidence index

Observed 2026-09-25. This index records historical execution and the later
candidate assessment without changing any original Gate record. The scenario
catalog and Gate dependencies remain in [gate-contract.json](gate-contract.json).
The [P2 inventory template](P2-INVENTORY-TEMPLATE.json) is an initialization
template; its `not_run` values are not a current execution summary.

## Historical reviewed Gates

All 40 scenarios in the four Gates below have direct scenario records marked
`passed`. Each Gate's `REVIEWED.json` reports `status=passed` and independent
`review.decision=pass`. The original source is commit
`b9a0f49f485d158d9f4095e6d60cbb8fcbeb8beb`, tree
`69641dd8dbbb526ed7514048d87627d27291e31e`, contract revision
`2026-09-22.11`. The records remain bound to their original private execution
profile, source and expiry. The following SHA-256 values were read back from
the original files on Linux host `1302-recovery` at
`/home/changgeng/acs-p2-b9a0f49-current/`.

| Gate | Scenarios passed | Reviewed record SHA-256 | Binding expiry (UTC) |
| --- | ---: | --- | --- |
| `P2-CODEX` | 8/8 | `c3e6a0050e0a1ded1fe19ebe1c9f032aac196a40716e58b78f509c5b6d14309d` | `2026-09-23T00:34:26.488506Z` |
| `P2-OPENCODE` | 8/8 | `360a5e62e826750361095b1813cb0ff1b37ec52683b3a923567a965b3586b7a4` | `2026-09-23T00:34:26.488506Z` |
| `P2-MCP-WORKFLOW` | 12/12 | `320a0dc354d537e48e77d50419607050edb573c9a61ff9ef1e92a567642f26a8` | `2026-09-23T00:21:45.381350Z` |
| `P2-MANAGEMENT-WORKFLOW` | 12/12 | `c78f1a812ea210dabf4253aafec69fab31e56600ec5f557b74fd61d585d4c1d6` | `2026-09-23T03:42:19Z` |

The independent technical review at the same source reports
`status=reviewed_awaiting_product_owner` and `review.decision=technical_pass`:
`P2-TECHNICAL-REVIEWED.json`, SHA-256
`706d4a937488bcea5d029d530e70e34eea68488ee8a847f4a73a5fcc7828414a`.
This technical result is distinct from the `P2-REVIEW` Gate's independent
candidate review and product-owner decision.

The original time-bound Machine, Session, Grant and endpoint observations have
expired. Their expiry does not change the historical execution result. Current
availability and final acceptance require current evidence for the selected
candidate and deployment.

## Later candidate and Control Parity

An independently reviewed private capability-continuity assessment at
`D:\Chatgpt\Agent-collaboration\.tmp\p2-2a58f11-capability-continuity.md`
at `2a58f1144a27a4ca84e1b6a8024d23b55998f34d` maps the historical P2
results to a later candidate using a source-delta check and selective current
readbacks. It records a separate P1 Gate with 18/18 scenarios, chained audits,
independent Review `pass`, and exact record SHA-256
`ad9263023ea4cdf8e4fb3d54fb373d3906bad84dbe32a48af0f1d3a326f34807`.
The assessment does not create new P2 Gate runs at that commit.

For the current `P2-CONTROL-PARITY` contract revision `2026-09-25.1`, the
required scenario set contains `P2-CONTROL-HANDOFF-ACK`. Private product
evidence at commit `8e6429b6035017d900683f64b83646df78fd196d`, tree
`a1a3aed1fb1a684f50264ccece8ee8edd47acd0a`, records a real Root-to-B
Codex handoff, durable Inbox delivery, authenticated acknowledgement,
rejection, Session replacement, ACK-loss replay, duplicate dispatch and
withdrawal. The independent review decision is `pass` for the scoped
`message_only` Inbox and MCP acknowledgement capability. The local decision
record is `D:\Chatgpt\Agent-collaboration\.tmp\p2-control-parity-evidence\handoff-product-gate-decision.json`,
SHA-256 `5505f3a3e0c555f502a6887ed5f42b62b5802e77880511347e58470676fb3e61`.
Its binding expired at `2026-09-24T22:42:33.227337Z`. The formal
`P2-CONTROL-PARITY` Gate record was not created in that run. Preserve the scoped
result and finish formal Gate assembly/review against the selected candidate;
do not label the executed scenario `not_run`.

ChatGPT Web and Desktop native Chat Turn wake is a Host applicability finding
under [the Control Parity contract](P2-CONTROL-PARITY-CONTRACT.md). It is not a
required scenario in revision `2026-09-25.1`.

## P2-REVIEW boundary

### v1.0.0 release candidate checkpoint — 2026-09-26

The tested public candidate snapshot on `codex/p2-v1-release` was commit
`bec582b52c98568f8eeee393d1d769c293f6ee49`, tree
`e2585dc1caac53504bd939edbccb00818d95735f`. The branch includes the
committed P1/P2 implementation, the owner-local installer, setup and knowledge
Skills, and product documentation under Sustainable Use License 1.0.

On Linux host `1302-1`, an isolated Compose project has healthy PostgreSQL and
Temporal. The installer registered this repository's Management Root and Route,
then read back `context_completeness=current`. Its local Codex and OpenCode MCP
entries each completed an MCP SDK handshake, discovered 36 tools, and returned
an authorized Profile and current project context. A separate candidate profile
created a Team and WorkItem through real stdio MCP and read back the WorkItem and
Inbox. Real PostgreSQL targeted tests passed: 16 Grant/team tests and 67 project
registration, MCP, Work and Review tests. These are scoped source and local
service observations; no ChatGPT Tunnel or cross-host first-use journey is
claimed by them.

Source-bound zip and tar archives were built at this candidate. Their SHA-256
values are `42831f88be15895d06fb381faf73c45d1ab9348e4bf1c95a174e158731f22c52`
and `655649bfcdefc1aa6d1c1827b968fc7fd7b5549c373de50e25b9550545b77aee`
respectively. The package manifest names the same commit/tree. GitHub Actions
for this SHA fail before runner allocation: the failed jobs have an empty runner
name, zero steps and an empty log archive. The CI Gate remains unverified.

Control Parity formal assembly, current-candidate independent review,
ChatGPT private Tunnel read/write/deny/reconnect/revoke, Windows and OpenCode
link-only cold starts, and the product-owner P2 decision remain open. The
historical reviewed Gate records retain their original source and expiry.

`P2-INDEPENDENT-GATE-REVIEW` and `P2-PRODUCT-OWNER-DECISION` remain `not_run`.
Before deciding the final Gate, bind the chosen integrated commit/tree, resolve
the Control Parity formal record, assess the source changes since the historical
Gates, refresh the live identity and authorization observations needed by the
release claims, and obtain independent review on that candidate. The product
owner then records the P2 decision. No AcceptedStateRevision, merge, tag or
Release is implied by the historical Gate passes or the scoped handoff result.
