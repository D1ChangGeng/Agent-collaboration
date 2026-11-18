---
id: HANDOFF-2026-11-18-PORPITA-UI-SPEC-CLOUD
task: PORPITA-UI-SPEC-CONTINUATION-AND-INTEGRATION
from_role: Coordinator/Executor/Reviewer (Local Windows Session)
to_role: Coordinator/Executor/Reviewer (Cloud Continuation Session)
created_at: 2026-11-18
status: ready
---

# Objective

Continue the `/ui-spec` workflow for `docs/client/porpita-ui-spec/` from the Round 89 baseline through all required multi-round iterations, expand and reconcile associated client UI SPECs/contracts (`R2`), and complete real default-build workbench integration and verification (`R3`) while strictly preserving pre-existing uncommitted work in `Agent-collaboration` and `Porpita` and recording honest environment boundaries.

# Actual result

Local multi-agent execution completed global discovery, milestone decomposition (`M1`–`M5` + parallel 4-tier E2E track), **Round 90 (`M1-A`) full implementation and 5-agent verification gate closure**, **Round 91 (`M1-B`) full source and unit-test implementation**, and **authoring + smoke hardening of the 87-test 4-tier opaque-box E2E suite**, then packaged all `.gitignore`-scoped/local artifacts into a portable cloud handoff directory:

1. **M1-A / Round 90 (`F01` + `F02`) — Completed & Gate-Approved**:
   - Sealed on branch `codex/porpita-ui-spec-90` at commit `492ba96e45b9f398bbbde0a2dd81b1f88a74d32c` (via `5c8531bc19` → `28c8847a98` → `492ba96e45`).
   - Resolved zh-CN mixed-English onboarding copy, main-process `main-i18n.ts`/`register-app-menu.ts` `'Porpita'` fallback strings, `OnboardingFlow` focus trapping and skip-confirmation cancel focus recovery (including disabled-prior-target fallback to `[data-onboarding-modal]`), `Landing.tsx` `600×400` vertical scroll reachability, `contextual-tour-gate.ts` 0-width/0-height collapsed `overflow: hidden` ancestor handling, `"Porpita Mobile"` / `"Porpita 手机端"` entry naming, and `ArtifactsPage` honest `Unavailable / 不可用` empty states when account auth is unconfigured.
   - Updated `docs/client/porpita-ui-spec/ITERATION_90.md`, `catalog/iteration-90-assurance.txt`, `tools/observe-round-90.cjs`, `evidence/iteration-90-windows/` (23 capture pairs), `source-index/*`, and `coverage-audit.json` (`本轮局部通过`: `119 -> 127`, `待验`: `247 -> 239`, `errors: []`).
2. **M1-B / Round 91 (`F03`: `P.*`, `P.13`, `Q.*` Visual, Accessibility & Motion Alignment) — Source & Unit Tests Committed**:
   - Sealed cleanly on branch `codex/porpita-ui-spec-91-wip` at commit `50a1e8645a98d9951182ac3d04bee77290a710d6` (40 files changed, `+1021 / -146` lines), with observation script at `docs/client/porpita-ui-spec/tools/observe-round-91.cjs`.
   - Implements `forced-colors: active` / `prefers-contrast: more` rules, `prefers-reduced-motion: reduce` across CSS and UI primitives (`dialog`, `sheet`, `tooltip`, `select`, `context-menu`, `command`, `accordion`, `switch`, `sonner`), `<html lang>` dynamic sync in `I18nProvider.tsx`, segmented-control/sidebar/zoom accessibility fixes, `P.13` locale completeness (`zh.json`, `zh-Hant.json`, `en.json`, `en-runtime-required.json`), and new unit test suites (`main-css-accessibility-motion.test.ts`, `ui-primitives-reduced-motion.test.tsx`).
   - `.tmp/porpita-ui-spec-03` working tree was restored cleanly to `codex/porpita-ui-spec-90` (`492ba96e45`) so `HEAD`, `out/`, and `coverage-audit.json` remain 100% synchronized at handoff time while `codex/porpita-ui-spec-91-wip` preserves all Round 91 code.
3. **4-Tier Opaque-Box E2E Verification Suite (`F11`) — Authored & Packaged**:
   - 12-file, 87-test suite (`Tier 1`: 36, `Tier 2`: 36, `Tier 3`: 8, `Tier 4`: 7) covering `J01`–`J13`, `T01`–`T12`, `UX01`–`UX22`, loopback ACS Core (`/api/communication/v1`), non-mutating UI SPEC structural audit, and `ENV_BOUNDED` honesty checks.
4. **Portable Cloud Handoff Package Created**:
   - `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/` contains the origin-anchored Git bundle (`porpita-ui-spec-from-origin-to-91wip.bundle`), plain-text patch series (`patches/0001..0004-*.patch`), clean `porpita-e2e-suite/` snapshot, `SHA256SUMS.txt`, and `CLOUD_CONTINUATION_GUIDE.md` (`M1`–`M5` blueprint).

# Files / artifacts changed

- `docs/client/porpita-ui-spec/`:
  - Added `ITERATION_90.md`, `catalog/iteration-90-assurance.txt`, `tools/observe-round-90.cjs`, `tools/observe-round-91.cjs`, `evidence/iteration-90-windows/*`
  - Updated `README.md`, `SOURCE_BASELINE.md`, `COVERAGE_CLOSURE.md`, `UI_INVENTORY.md`, `COVERAGE_MATRIX.md`, `coverage-matrix.csv`, `coverage-audit.json`, `catalog/*.psv`, `evidence/observations.json`, `source-index/*`
- `.agents/coordination/handoffs/2026-11-18-porpita-ui-spec-cloud-handoff.md` (this handoff record)
- `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/`:
  - `porpita-ui-spec-from-origin-to-91wip.bundle` (`1,800,795` bytes, SHA-256 `8985224c7bb5e611ff26f4f48b6ba5b4b43542d81f7864f86491a78e09e9cada`, anchored at `517555d5ce68ba8e417cdd2192b561a4061237ef`)
  - `patches/0001-Fix-F01-onboarding-landing-tour-l10n-and-focus-F02-P.patch` (SHA-256 `f461585e7edbffc1dc03f6a14426fb0c21fececb20d9e756d600879baed1216f`)
  - `patches/0002-Fix-main-process-English-Orca-leaks-onboarding-skip-.patch` (SHA-256 `c1939d2ffff5ff191447131636126f3620fb92889d45e0a7f9dde41fd0d33dd3`)
  - `patches/0003-Fix-disabled-onboarding-skip-confirm-focus-fallback-.patch` (SHA-256 `428ff291481f4b75cb9e454239cc7432e71ee22e1f9173602ada5b535187b8c1`)
  - `patches/0004-WIP-round-91-implement-F03-P.-P.13-Q.-high-contrast-.patch` (SHA-256 `d0f7d24094079a009dd2346899a68196d0d49c626aaed419ac8aa5d62f9f2ba4`)
  - `porpita-e2e-suite/` (clean 12-file copy of `.tmp/porpita-e2e-suite/`)
  - `CLOUD_CONTINUATION_GUIDE.md` & `SHA256SUMS.txt`
- Local gitignored `.tmp/` state (preserved in place and mirrored into `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/`):
  - `.tmp/porpita-ui-spec-03` (`codex/porpita-ui-spec-90` @ `492ba96e45`, plus branch `codex/porpita-ui-spec-91-wip` @ `50a1e8645a`)
  - `.tmp/porpita-e2e-suite/`

# Verification

- **Round 90 (`492ba96e45`)**: 5-project TypeScript check (`0` errors), localization catalog check (`21,902` refs, exit `0`), `lint-staged` (`oxlint`/`ast-grep`/`oxfmt` pass), 48/49 Vitest files passed (1 platform-skipped), 7 live isolated Electron CDP challenge launches passed (`0` menu/UI `'Orca'` leaks in en/zh, `600×400` bounds & focus recovery verified), 5-agent Verification Wave `PASS` (`2` Reviewers `APPROVE` + `2` Challengers `PASS` + Forensic Auditor `CLEAN`).
- **Round 91 WIP (`50a1e8645a`)**: Passed l10n checks, `oxlint`/`oxfmt`, 5-project TypeScript (`0` errors), targeted Vitest (`13/13` files, `104/104` tests), and `git diff --check`.
- **E2E Suite**: Passed isolated `spec-audit-harness` (`20` domains, `371` rows, `0` broken links, `35` API ops parity), `acs-core-harness` (ephemeral PostgreSQL + loopback FastAPI), and post-fix Tier 1 `--mode smoke` (`6/6` passed).
- **Git Bundle & Hygiene**: `git bundle verify` passed on `porpita-ui-spec-from-origin-to-91wip.bundle`; 84 temporary `%TEMP%\porpita-*` directories cleaned (`0` remaining); `0` orphaned E2E processes or containers; pre-existing uncommitted files in `Agent-collaboration` (`15` tracked modified files) and `Porpita` (`189` porcelain entries) verified intact.

# Unresolved items and risks

1. **Remaining Milestones (`M1-B` completion → `M5`)**:
   - **M1-B (Round 91)**: Needs `out/` rebuild on `codex/porpita-ui-spec-91-wip` (`50a1e8645a`), live Electron replay via `tools/observe-round-91.cjs`, `ITERATION_91.md` + `catalog/iteration-91-assurance.txt`, and `source-index.cjs` + `build_coverage.py`.
   - **M1-C (Rounds 92–93)**: Retained local workbench tools verification (`H.*`, `I.*`, `L.01–L.03, L.05–L.06`, `N.*` non-collab + `N.repo`, `O.*` local).
   - **M2 (Rounds 94–96)**: ACS Collaboration & Core state sync (`N.general.01` reconnect lag fix, `"尚未连接工作区"` → `"协作项目"` naming, `K.*` / `C.10.08` loopback Core verification against `docs/client/communication-*`).
   - **M3 (Rounds 97–101)**: Promote `WorkspacePreview`, top-level `TabGroup` (`D.07*`/`D.08*`), `SidebarSessionIndex` (`C.10*`), and pinned `SidePanel` (`G.09*`) into the default production workbench shell (removing `VITE_PORPITA_WORKSPACE_PREVIEW` gate while preserving legacy profile fallback) and replay `J01`–`J13`.
   - **M4 (Round 102)**: Reconcile `docs/client/ORCA-FIRST.zh-CN.md`, add `Porpita-Workspace-UI-Spec-Reference-v1.0.0` (11 deliverables + Open #1–#12) and `communication-*` crosswalks, run `source-index.cjs` / `build_coverage.py` / `check_design_evidence.py`, and finalize honest `COVERAGE_CLOSURE.md` boundaries.
   - **M5**: Run full 87-test 4-tier opaque-box E2E verification (`--mode full`) + adversarial coverage hardening.
2. **Cloud OS Adaptation Risk**:
   - Local runs used Windows x64 (`ORCA_BACKGROUND_LAUNCH=1` + `taskkill` fallback in `porpita-e2e-suite/lib/electron-harness.mjs`). On a Linux cloud container/VM, Electron launches should run under isolated `Xvfb` or headless Wayland (`--ozone-platform=wayland` / `xvfb-run`), and `electron-harness.mjs` teardown should use POSIX process-group signals (`SIGTERM`/`SIGKILL`) when `process.platform !== 'win32'`.
3. **Untracked Repository Paths Risk**:
   - `docs/client/porpita-ui-spec/`, `.agents/coordination/handoffs/2026-11-18-porpita-ui-spec-cloud-handoff.md`, and `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/` are currently untracked (`LOCAL_ONLY`) in `Agent-collaboration` to avoid interfering with the 15 pre-existing modified tracked files. Ensure these directories are uploaded/synced or committed on a dedicated handoff branch before opening the cloud session.

# Repository Sync

1. **`Agent-collaboration` (`D1ChangGeng/Agent-collaboration`)**:
   - Branch: `codex/porpita-ui-spec-cloud-20261118` (branched from `origin/main` `e5d71968a13e67e3dc51e318867d4ed9a1f946ac`; local `main` working tree & index left untouched)
   - Base commit: `e5d71968a13e67e3dc51e318867d4ed9a1f946ac`
   - Head commit: pushed tip of `origin/codex/porpita-ui-spec-cloud-20261118` (includes the 15 runtime/NativeLink updates, full `docs/client/`, `RFC_TEMP_SOURCE/Porpita-*`, this handoff record, and `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/` with `porpita-history-root/`)
   - Working tree (on pushed branch): `clean` (`PUSHED_RECEIVER_PULL_REQUIRED`)
   - Push: `yes` (`origin/codex/porpita-ui-spec-cloud-20261118`)
   - Receiver sync: `fetch` (`git fetch origin codex/porpita-ui-spec-cloud-20261118 && git checkout codex/porpita-ui-spec-cloud-20261118`)
2. **`Porpita` (`D1ChangGeng/Porpita`)**:
   - Branches pushed:
     - `codex/porpita-ui-spec-87`: `df72b79763023cbb84724c37c5ba4fcb435303fd` (Round 89 baseline)
     - `codex/porpita-ui-spec-90`: `492ba96e45b9f398bbbde0a2dd81b1f88a74d32c` (Round 90 Gate-verified baseline)
     - `codex/porpita-ui-spec-91-wip`: `50a1e8645a98d9951182ac3d04bee77290a710d6` (Round 91 F03 source + 104 passing unit tests)
   - Working tree: `clean` (`PUSHED_RECEIVER_PULL_REQUIRED`)
   - Push: `yes` (`origin/codex/porpita-ui-spec-87`, `origin/codex/porpita-ui-spec-90`, `origin/codex/porpita-ui-spec-91-wip`)
   - Receiver sync: `fetch` (`git fetch origin codex/porpita-ui-spec-90 codex/porpita-ui-spec-91-wip`)
3. **`Porpita` Candidate 11 Historical Archive (`--history`)**:
   - Packaged directly inside `Agent-collaboration` at `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/porpita-history-root/` (`docs/porpita/evidence/20261109/installed11-*.json` + `docs/porpita/handoff/*`) so `build_coverage.py --history` and `run-e2e.mjs --history-root` work standalone in the cloud.

# Knowledge / decision updates

- Round 90 design/implementation evidence and coverage decisions are recorded in `docs/client/porpita-ui-spec/ITERATION_90.md`, `COVERAGE_CLOSURE.md`, `SOURCE_BASELINE.md`, and `coverage-audit.json`.
- Associated UI SPEC topology (`ORCA-FIRST.zh-CN.md`, `communication-*` OpenAPI/adoption contracts, `Porpita-Workspace-UI-Spec-Reference-v1.0.0`, and archived 2026-11-06 client docs boundary) and the full `M1`–`M5` + 4-tier E2E execution contract are persisted in `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/CLOUD_CONTINUATION_GUIDE.md`.

# Required next action

1. Ensure the cloud session has `Agent-collaboration` (including `docs/client/`, `.agents/coordination/handoffs/2026-11-18-porpita-ui-spec-cloud-handoff.md`, `integration_evidence/porpita-ui-spec-cloud-handoff-20261118/`, and `RFC_TEMP_SOURCE/Porpita-*` if crosswalk inspection is needed) plus a `Porpita` clone containing `517555d5ce68ba8e417cdd2192b561a4061237ef`.
2. In the cloud session, verify `SHA256SUMS.txt`, fetch `codex/porpita-ui-spec-90` (`492ba96e45`) and `codex/porpita-ui-spec-91-wip` (`50a1e8645a`) from `porpita-ui-spec-from-origin-to-91wip.bundle`, stage `porpita-e2e-suite/`, and execute `M1-B` completion → `M1-C` → `M2` → `M3` → `M4` → `M5` following `CLOUD_CONTINUATION_GUIDE.md` and the `ui-spec` skill.

# Reply required

Yes. When the cloud session completes `M1-B` through `M5`, return a completion handoff reporting final Porpita & `Agent-collaboration` commit SHAs, `coverage-audit.json` summary, 4-tier E2E report results, and updated `COVERAGE_CLOSURE.md` environment boundaries.
