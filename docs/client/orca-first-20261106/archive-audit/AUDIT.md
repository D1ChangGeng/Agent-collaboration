# Client documentation archive audit — 2026-11-06

Pre-archive inventory, 2026-11-06. Repository source baseline: `codex/core-cleanup@19d7881d49ee887315c54c5bc02e0cc424061376`. The inventory records the original document bytes and evidence files before governance edits. It does not assert a clean working tree or current product acceptance.

## Recommended disposition

Archive the **entire former Client product/UX/development-planning corpus in place**, with an explicit archive index and a single new current ORCA-first / plugin-first decision source. Keep original paths and assets. “In place” must mean an authoritative scope-wide status change, not merely a candidate label at the top of selected files.

The archive declaration should state that every former Client product-form choice, confirmed UI, implementation requirement, Core gap backlog, confirmation sequence, and P3/P4 Client delivery plan is historical and no longer constrains new development. Historical “confirmed”, “final confirmation”, “implement”, “must”, “acceptance” and “next phase” expressions retain their original dated meaning only. New requirements enter through the new decision source. Runtime/Core's independently current contracts remain current.

There is no current `docs/client/README` or other directory index. Existing entry is the root READMEs, then PRODUCT-REVIEW, then WORKBENCH-ADOPTION. Replace that entry chain with the new decision source and an archive index.

## Complete corpus inventory

`inventory.json` records all 364 files (83,236,419 bytes) and SHA-256 before any parent changes. Assets are 356 files; top-level deliverables are 8. It is a preservation baseline, not an assertion that every document's old product conclusions remain valid.

| Corpus | Files | Bytes | Disposition |
|---|---:|---:|---|
| Eight top-level deliverables below | 8 | 856,217 | Historical baseline / historical research |
| `docs/client/review-20261105/` | 63 | 41,688,818 | Historical research and evidence bundle |
| `docs/client/communication-20261105/` | 141 | 13,916,808 | Historical research/prototype; evidence reusable within limits |
| `docs/client/workbench-20261106/` | 152 | 26,774,576 | Historical adoption research; source/media facts reusable within limits |

## Historical design baselines

| Exact file | Present title/status | Necessary scope clarification |
|---|---|---|
| `docs/client/UX-DESIGN.zh-CN.md` | `ACS Client 页面与交互设计基线`; top block calls it history v1.52, but line 12 status still says confirmed design target | Historical baseline in title/status; line 17/19's confirmed rules and uniform routing are historical; no direct implementation obligation |
| `docs/client/USER-FLOWS.zh-CN.md` | `ACS Client 用户流程与能力规划`; 570,637 bytes; top history v0.59, but line 12 is a live confirmation status | Historical baseline in title/status; all old confirmation/implementation/acceptance clauses have no current binding effect, including entire §2, §4 confirmation map, §6 Core gaps, §8 remaining decisions and P3/P4 planning |

Especially material USER-FLOWS locations: line 19 says to use UX's confirmed rules; line 29 says implement according to confirmed entries; line 33 says “按已定规则做技术设计、实现及验收”; line 522 references final confirmed session strategy; §4 starts line 3105; §8 starts line 4066; line 4111 still registers P3/P4 delivery scope and order; ED02 at 4187 classifies future commercial product scope. Its EA/EB/ED evidence records stay attached to their original commit/date and do not become current facts automatically.

## Historical research and duplicate deliverables

| Exact files | Present title/status | Archive treatment |
|---|---|---|
| `docs/client/PRODUCT-REVIEW.zh-CN.md`, `PRODUCT-REVIEW.html` | `ACS Client 产品形态复核与目标方案`; 2026-11-05 candidate pending user confirmation | Both historical product research. MD:15 / HTML:41 currently calls WORKBENCH “当前采用研究”; replace current authority wording with archive linkage and new-current link |
| `docs/client/COMMUNICATION-EXPERIENCE.zh-CN.md`, `COMMUNICATION-EXPERIENCE.html` | `ACS Client 通讯与关联阅读体验研究`; candidate reading layout | Both historical UX research; MD:5 routes to WORKBENCH; MD:196 says next phase must confirm this experience. It cannot remain a live required confirmation gate |
| `docs/client/WORKBENCH-ADOPTION.zh-CN.md`, `WORKBENCH-ADOPTION.html` | `ACS × Orca 工作台采用研究与改造边界`; 2026-11-06 product/adoption plan pending confirmation | Both historical adoption research, including candidate alternatives, §8 A–E experiments, §9 current document roles, §10 pending decisions. A new ORCA-first decision supersedes it rather than silently promoting this prior candidate |

All 3 HTML files duplicate MD contents and must receive matching archived title/H1/status/current-source links. Otherwise direct HTML bookmarks remain misleading.

## Reusable factual evidence (archived research, not current product authority)

| Exact entry | Reusable evidence | Boundary |
|---|---|---|
| `review-20261105/research/RESEARCH-NOTES.md`, `ASSET-INVENTORY.json`, figures, official images/media and CSS license | Six products' observed official visuals and sampled media states; provenance | No owner acceptance, native runtime, latency or continuous-flow proof |
| `communication-20261105/research/WINDOWS-VISUAL-NOTES.md` | Actual pixels and explicit missing/unobtained sources | No inference from missing screenshots; static appearance only |
| `communication-20261105/research/ACS-DESKTOP-VERIFICATION.md` | Local fixture interaction observations | No ACS/Harness/model connection; fixture validation is not product acceptance |
| `communication-20261105/sources/SOURCES.md`, `source-inventory.json`, Pigi/T3/Paseo snapshots and licenses | Fixed source/license/dependency research | Not complete App adoption or build evidence |
| `communication-20261105/prototype/ADOPTION.md`, source, dist, verification JSON/images, vendor and notices | Pigi presentation trial, reply graph/anchor fixture behavior and recorded checks | Historical runnable prototype; no Core integration; do not alter assets to look like current product |
| `workbench-20261106/adoption-research/adoption-findings.md`, `source-manifest.json`, fixed Orca/T3 snapshots | Orca/T3 contracts, plugin contribution limits, durable orchestration overlap, license provenance | Pinned Orca `9055eb9…` and T3 `938b4d4…`; source-only, no installed runtime or build validation |
| `workbench-20261106/core-bridge/acs-orca-core-feasibility.md` | Actual ACS receiver factory seams; admission/dedup/single-session-owner/reply responsibilities | Source feasibility only; no Orca receiver implementation or runtime qualification |
| `workbench-20261106/official-research/BEHAVIOR-NOTES.md`, `VERIFIED-SCREENSHOTS.json`, screenshots/crops | Observed public website states and operated website controls | Marketing presets; not installed App execution or response/performance evidence |
| `workbench-20261106/user-media/EVIDENCE-NOTE.md`, metadata, screenshots, curated frames and manifests | User-supplied website recordings; sampled temporal ordering | Original videos remain outside repo and are not copied; sampled marketing sequence only |
| `workbench-20261106/ui-source/README.md`, `source-manifest.json`, 4 full files and sidebar excerpt | Pinned presentation ownership and existing workspace continuity mechanisms | Not a complete buildable checkout or permission to reconstruct missing UI |
| `PRODUCT-REVIEW.zh-CN.md` §1 C01–C16 | Static ACS 2.3.1 source findings linked to actual Core contracts/tests | Consult current contracts/code first; dated audit is not an independent replacement contract |

The new current decision can cite these exact factual records. Revalidation is required where version, environment or product scope changes. Research recommendations and proposed UI remain archived even if source facts are reused.

## External reference and authority conflicts

| Referrer | Exact lines / current role | Safe update |
|---|---|---|
| `README.md` | 244–248: PRODUCT-REVIEW main entry; UX and Flows history | Point first to single new current decision; give explicit archive index link |
| `README.zh-CN.md` | 197–200: same structure | Same current/archive split |
| `agent-collabration/routes/collaboration-runtime/design/BUSINESS-MODEL.zh-CN.md` | 303 labels UX and Flows Client product design; 40–44, 225–230, 288 describe former Client/read-only Agent responsibility | Narrow Client-specific historical cross-reference. Do not archive this entire Core business document or rewrite its independent current contracts |
| `.../design/CLEANUP-IMPLEMENTATION-STATE.md` | 7, 172, 319 record preservation of user docs | Historical operational record; leave as-is |
| `.../design/MACHINE-FILESYSTEM-VERIFICATION.zh-CN.md` | 159 records preserved docs | Historical verification record; leave as-is |
| `communication-20261105/research/WINDOWS-VISUAL-NOTES.md` | Internal study references | Retain as evidence relationships; archive boundary resolves authority |

Root `.agents/coordination/routes.yaml` contains only active `collaboration-runtime`; no separate Client route exists. Route AGENTS and route knowledge index do not reference old Client docs. The single knowledge entry is active `guides/p2-cross-machine-runtime.md`; leave it intact. Broad `.agents/runtime/bootstrap/upgrade-instruction.txt` P3/P4 content is old Runtime bootstrap material, not the Client plan and not scope for a blanket Client archive operation. `docs/runtime/UPGRADE-CONTRACT.md:33` retains independently named future P3/P4 profiles; leave its Core contract authority intact.

## Why preserve paths

Moving all former material to `archive/` would change relative links to Core `../../runtime`, `../runtime`, image folders, prototype assets and CSS. Moving only the top-level MD/HTML would break their relative media links; moving the whole subtree changes Core/source paths. In-place archive is the lowest-risk complete archive: indexed collection status + per-entry explicit status + superseding authority + current entry rerouting. If physical relocation is later chosen, it needs a complete link rewrite and old-path redirects/stubs, followed by browser/media/prototype validation. Physical deletion is unnecessary.

## Archive governance and validation scope

1. Create one current ORCA-first / plugin-first decision source, with exact adopted behavior and authority boundary, plus an explicit archive index listing all 8 top-level files and all 3 bundles.
2. Set titles/H1/status on all 5 MD and all 3 HTML to historical, link the new current source and archive index, and explicitly void former confirmation/implementation/acceptance/phase-planning authority across each complete document.
3. Replace especially prominent old “current”, “next phase”, “implement as confirmed” routing in the introductions/status tables and WORKBENCH §9–10 with historical wording. Keep original technical records intact.
4. Update both root README entries and the narrowly relevant BUSINESS-MODEL Client cross-reference/paragraph notes. Keep route registry and current Core contracts unchanged.
5. Add clear collection-level archive explanation covering all evidence bundles and the prototype. Avoid bulk editing copied upstream source, licenses, media, checksums or fixture implementation.

## Validation checklist

- All 8 old top-level entry paths display historical status and link to the one current decision source; all three HTML titles/H1 and visible banners agree with MD.
- USER-FLOWS's historical scope explicitly includes all confirmed/final-confirmed UI, Core-gap requests, acceptance clauses, §4/§8 and P3/P4 plans; there is no inherited obligation merely because the old record says confirmed.
- WORKBENCH is archived prior research; it is not promoted to current by PRODUCT-REVIEW or another stale link.
- Current README navigation leads directly to ORCA-first; archive remains discoverable as history.
- Existing relative links, images, CSS, and prototype dist still resolve. No DESIGN-MAP is recreated.
- Compare `inventory.json`: asset files, copied sources, licenses, manifests and media hashes unchanged; only explicitly edited historical entry documents differ.
- Git diff contains documentation governance only, preserves existing user changes, and does not modify Runtime/Core code/contracts or route identities.
- No claim of installed Orca, plugin capability, real ACS bridge, native execution, build, runtime test or owner acceptance is invented by archiving.
