# Porpita UI SPEC 云端续跑执行指南（2026-11-18）

本目录将本机多轮执行（直至第 90 轮门禁闭环 + 第 91 轮源码/单测 WIP + 4 层 87 项黑盒 E2E 验证套件）的所有产物整理为**可跨主机/云端会话无损恢复**的交接包，摆脱对本机 `.gitignore` 目录（`.tmp/`）和 `%USERPROFILE%\.gemini` 临时目录的依赖。

## 1. 目录内容清单

- `porpita-ui-spec-from-origin-to-91wip.bundle`：自 `D1ChangGeng/Porpita` 远端基线 `517555d5ce68ba8e417cdd2192b561a4061237ef`（`codex/porpita-desktop`）起的完整增量 Git Bundle（约 1.8 MB），内含三个分支引用：
  - `refs/heads/codex/porpita-ui-spec-87` → `df72b79763023cbb84724c37c5ba4fcb435303fd`（第 89 轮起始基线）
  - `refs/heads/codex/porpita-ui-spec-90` → `492ba96e45b9f398bbbde0a2dd81b1f88a74d32c`（**第 90 轮 M1-A 已通过 5 智能体门禁并对齐 `coverage-audit.json`**）
  - `refs/heads/codex/porpita-ui-spec-91-wip` → `50a1e8645a98d9951182ac3d04bee77290a710d6`（**第 91 轮 M1-B `F03` 全部 40 个源码与单测文件已提交，待构建/回放与规范文档落盘**）
- `patches/0001..0004-*.patch`：第 90 轮（3 个提交）与第 91 轮 WIP（1 个提交）的纯文本 `git format-patch` 补丁序列，便于直接审阅或 `git am`。
- `porpita-e2e-suite/`：完整的 4 层（共 87 项）需求驱动黑盒 E2E 测试套件快照（对应本机 `.tmp/porpita-e2e-suite/`，不含缓存或 `node_modules`）。
- `porpita-history-root/`：Candidate 11 历史证据与交接记录快照（含 `docs/porpita/evidence/20261109/installed11-*.json` 对应 `H01`–`H07` 及 `docs/porpita/handoff/*`），供云端直接传给 `build_coverage.py --history` 与 `run-e2e.mjs --history-root`。
- `SHA256SUMS.txt`：Bundle 与补丁文件的 SHA-256 校验和。

---

## 2. 云端会话快速恢复命令

远端推送已完成：
- **`D1ChangGeng/Porpita`（`origin`）**：已直接推送 `codex/porpita-ui-spec-87`（`df72b79763`）、`codex/porpita-ui-spec-90`（`492ba96e45`）与 `codex/porpita-ui-spec-91-wip`（`50a1e8645a`）三个分支（本目录 `.bundle` 同时保留作离线备份）。
- **`D1ChangGeng/Agent-collaboration`（`origin`）**：已推送分支 `codex/porpita-ui-spec-cloud-20261118`（包含完整 `docs/client/`、`RFC_TEMP_SOURCE/Porpita-*`、本交接包及运行端 NativeLink 补丁）。

在云端会话检出两仓库后：

```bash
# 1. Agent-collaboration 切至云端交接分支
git -C <AGENT_COLLAB_ROOT> fetch origin codex/porpita-ui-spec-cloud-20261118
git -C <AGENT_COLLAB_ROOT> checkout codex/porpita-ui-spec-cloud-20261118

# 2. Porpita 获取已推送的 90 / 91-wip 分支并检出（或在隔离工作树检出）
git -C <PORPITA_REPO> fetch origin codex/porpita-ui-spec-87 codex/porpita-ui-spec-90 codex/porpita-ui-spec-91-wip
git -C <PORPITA_REPO> checkout codex/porpita-ui-spec-90

# 3. 恢复隔离黑盒 E2E 套件到 .tmp/porpita-e2e-suite
mkdir -p <AGENT_COLLAB_ROOT>/.tmp/porpita-e2e-suite
cp -R <AGENT_COLLAB_ROOT>/integration_evidence/porpita-ui-spec-cloud-handoff-20261118/porpita-e2e-suite/* <AGENT_COLLAB_ROOT>/.tmp/porpita-e2e-suite/

# 4. 验证当前第 90 轮 UI SPEC 基线结构检查 0 错误（使用随包携带的 porpita-history-root）
python3 <AGENT_COLLAB_ROOT>/docs/client/porpita-ui-spec/tools/build_coverage.py \
  --source <PORPITA_REPO> \
  --history <AGENT_COLLAB_ROOT>/integration_evidence/porpita-ui-spec-cloud-handoff-20261118/porpita-history-root
```

---

## 3. 已完成进度与剩余里程碑蓝图（M1 → M5）

### 已完成：M1-A（第 90 轮：`F01` + `F02`）— **GATE PASS**
- **分支 / 提交**：`codex/porpita-ui-spec-90` @ `492ba96e45b9f398bbbde0a2dd81b1f88a74d32c`（历经 `5c8531bc19` → `28c8847a98` → `492ba96e45` 三轮收敛，通过 2 Reviewers + 2 Challengers + Forensic Auditor 终审）。
- **交付物**：
  - 修复 `OnboardingFlow` 简中英文混杂、主进程 `main-i18n.ts`/`register-app-menu.ts` `'Porpita'` 回退、跳过确认弹窗取消回焦（含原目标变为 `disabled` 时安全回退模态根，不落入 `document.body`）、`Landing.tsx` `600×400` 窄窗滚动、`contextual-tour-gate.ts` 0 宽高折叠 `overflow: hidden` 祖先误判修复。
  - 统一 `Porpita Mobile` / `Porpita 手机端` 入口命名（保留上游客户端下载说明）、校对 `PhoneCarousel`/`TerminalSlide` 译文；`ArtifactsPage` 未配置账户服务时呈现诚实 `Unavailable / 不可用` 状态与返回工作区动作。
  - 文档与证据：`docs/client/porpita-ui-spec/ITERATION_90.md`、`catalog/iteration-90-assurance.txt`、`tools/observe-round-90.cjs`、`evidence/iteration-90-windows/`（23 组快照）、`coverage-audit.json`（`本轮局部通过` 119 → 127，`待验` 247 → 239，`errors: []`）。

### 进行中：M1-B（第 91 轮：`F03` 视觉、无障碍与动效系统 `P.*` / `P.13` / `Q.*`）— **源码与单测已就绪**
- **分支 / 提交**：`codex/porpita-ui-spec-91-wip` @ `50a1e8645a98d9951182ac3d04bee77290a710d6`（40 个文件，`+1021 / -146` 行），观察脚本已位于 `docs/client/porpita-ui-spec/tools/observe-round-91.cjs`。
- **已完成部分**：
  1. 高对比与 `forced-colors: active` / `prefers-contrast: more`（`main.css`）；
  2. 减少动态（`prefers-reduced-motion: reduce` 覆盖 `main.css`、`markdown-preview.css`、`rich-markdown-editor.css`、`mobile-page.css`、`terminal.css`、`components/ui/*` 及外观设置）；
  3. 无障碍与 `<html lang>` 动态同步（`I18nProvider.tsx`、`index.html`、`UIZoomControl.tsx`、`SettingsFormControls.tsx`、`SettingsSidebar.tsx`、`drop-indicator.ts`、`AppWorkspaceShell.tsx`）；
  4. `P.13` 多语言补齐（`zh.json`、`zh-Hant.json`、`en.json`、`en-runtime-required.json`）及新增单测（`main-css-accessibility-motion.test.ts`、`ui-primitives-reduced-motion.test.tsx`，13 文件 104 项单测已在本机通过）。
- **云端接手首步动作**：
  1. 将工作树切至 `codex/porpita-ui-spec-91-wip`（或合入新分支 `codex/porpita-ui-spec-91`），执行子包与 `electron-vite` 构建；
  2. 运行 `tools/observe-round-91.cjs`（在云端 Linux 环境可结合 Xvfb/Wayland 隔离显示运行 Electron 采集真实证据）；
  3. 编写 `ITERATION_91.md`、`catalog/iteration-91-assurance.txt`，更新 `catalog/*.psv`、`evidence/observations.json`、`README.md`、`SOURCE_BASELINE.md`、`COVERAGE_CLOSURE.md`；
  4. 运行 `node tools/source-index.cjs` 与 `python3 tools/build_coverage.py` 确保 `errors: []`。

### 待执行：M1-C（第 92–93 轮：`F04` 保留本地工作台工具验证收口）
- 实机/隔离构建验证保留工具域：`H.01–H.06`（编辑器/专用查看器/Diff/Git Graph）、`I.01–I.04.01`（本地 HTTP Browser/页内查找/DevTools/扩展工具栏）、`L.01–L.03, L.05–L.06`（Automations 含窄窗工具栏防重叠、Skills、合成插件）、`N.*` 非协作分区 + `N.repo`、`O.*` 本地弹层/菜单/通知；严格保持外部 OAuth/云端受限项为诚实 `待验`。

### 待执行：M2（第 94–96 轮：`F05` + `F06` ACS 协作与 Core 状态同步）
- **F05（`N.general.01` + `F04` 命名）**：消除 Settings 与标题栏连接状态在二次重连时的刷新滞后；将协作对话框 `"尚未连接工作区"` 对齐为 `"协作项目"`（区分执行工作树、协作项目 `project_id` 与 Porpita 工作空间）。
- **F06（`K`, `K.01–K.04`, `C.10.08`, `R.09`, `R.12`）**：基于隔离回环 ACS Core（可复用 `porpita-e2e-suite/lib/acs_loopback_server.py`）对照 `docs/client/communication-{openapi.yaml,p1-openapi.yaml,api-scope.json,contract-adoption.json}` 验证 `NativeLink`、`include_native_source`、`Draft`、`Notice`、`getSnapshot`/`subscribeEvents`、消息搜索与附件链路。

### 待执行：M3（第 97–101 轮：`F07` + `F08` 默认构建主壳层真实集成）
- **F07**：移除 `VITE_PORPITA_WORKSPACE_PREVIEW` 预览开关隔离，将 Workspace 切换器、顶层 Tab Group（`D.07*`, `D.08*`）、`SidebarSessionIndex`（`C.10*`）及固定范围 `SidePanel`（`G.09*`, `G.03–G.05`）正式集成进默认生产工作台并保留旧档案平滑迁移回退。
- **F08**：在默认构建上验证真实分屏拖放（`T.03`）、关闭/停放/未保存确认/焦点恢复（`D.01–D.05`, `T.06`, `S.09`）、快捷键层级（`N.shortcuts`）、退出持久化（`A.05`）及本地可运行的 `J01–J13` 全旅程回放。

### 待执行：M4（第 102 轮：`F09` + `F10` 关联 UI SPEC 扩展对齐与环境边界收口）
- **关联规范对齐（R2）**：
  1. 更新 `docs/client/ORCA-FIRST.zh-CN.md`：补充现行实现状态说明与双向交叉引用（映射 `T01–T12` / `UX01–UX22` 至 `porpita-ui-spec` 的 `J01–J13` 与 `K.*`，保留 2026-11-06 历史决策正文）；
  2. 在 `porpita-ui-spec/DECISIONS_AND_SEQUENCE.md` 与 `README.md` 补齐对 `RFC_TEMP_SOURCE/Porpita-Workspace-UI-Spec-Reference-v1.0.0/`（11 项交付物与 Open Questions #1–#12）及 `docs/client/communication-*` 契约的映射表；
  3. 对齐 `SOURCE_BASELINE.md` 中 `docs/porpita/{BRAND,DELIVERY,PLATFORMS}.md` 与 `handoff/*` 说明；
  4. 保持 `docs/client/{UX-DESIGN,USER-FLOWS,PRODUCT-REVIEW,COMMUNICATION-EXPERIENCE,WORKBENCH-ADOPTION}.zh-CN.md` 已归档只读状态。
- **全量审计与诚实边界（R3）**：运行 `source-index.cjs`、`build_coverage.py` 与 `ui-spec/scripts/check_design_evidence.py`，在 `COVERAGE_CLOSURE.md` 精确列明所有受真实账号/外部 SaaS OAuth/多物理主机/特定硬件或操作系统限制的待验边界，严禁虚报关闭。

### 待执行：M5（最终验收：4 层 87 项黑盒 E2E 全通 + 对抗加固 + 基线保护核验）
- 运行 `porpita-e2e-suite/run-e2e.mjs --tier all --mode full`（Tier 1: 36、Tier 2: 36、Tier 3: 8、Tier 4: 7，共 87 项用例，注：云端为 Linux 时需将 `electron-harness.mjs` 中的 Windows 进程清理分支适配 POSIX 信号清理）。
- 复核既有未提交改动未被触碰（遵守 `AGENTS.md`）。
