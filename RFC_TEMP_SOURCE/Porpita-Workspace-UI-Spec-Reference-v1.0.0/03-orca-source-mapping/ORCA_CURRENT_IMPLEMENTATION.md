# Orca / Porpita 当前 UI 实现映射

**参考代码基线：** `D1ChangGeng/Porpita` 分支 `codex/porpita-desktop`，提交 `517555d5ce68ba8e417cdd2192b561a4061237ef`；继承 Orca 上游基线 `26179069b664b2fc172963564ed419d97892b6c9`。Codex 开始 UI SPEC 时仍需确认本地工作树与此基线一致。

## App Shell 与 Titlebar
`src/renderer/src/app-shell/AppWorkspaceShell.tsx`：组合 Left Sidebar、Main Workspace、RightSidebar；Titlebar 使用 `TitlebarLeftControls` 和 `TitlebarMainStrip`；Active View 还包含 Settings、Skills、Artifacts、Tasks、Automations、Activity、Space、Mobile、Terminal 等页面。

`src/renderer/src/app-shell/TitlebarMainStrip.tsx`：`#titlebar-tabs` 是顶部标签渲染挂载点；Titlebar 还承担 pane expand、RightSidebar toggle 和 window-control spacer。它本身不是完整 Tab 数据模型。

## 当前 Tab / Pane
`src/renderer/src/store/slices/tabs/tabs-slice-contract.ts`：
- `unifiedTabsByWorktree`
- `groupsByWorktree`
- `activeGroupIdByWorktree`
- `layoutByWorktree`
- create/activate/close/reorder/move/drop/split ratio 等动作。

已有成熟 tab group、split tree、drag/drop、active group 和 layout persistence；但这些数据按 Worktree ID 索引，不等于跨 Project 的 Porpita Workspace。不能把 `worktreeId` 简单改名成 `workspaceId`。

## 当前 Sidebar
`src/renderer/src/components/sidebar/index.tsx`：包含 SidebarHeader、SidebarNav、WorktreeList、SidebarAgentsList、Workspace Board 等；Workspaces 与 Agents Activity 是不同视图。

`src/renderer/src/components/sidebar/SidebarAgentsList.tsx`：实际使用 `ActivityThreadListPane` 和 `useAgentPaneThreads`；选择 thread 的行为是 reveal 对应现有 Pane。它不是完整 Native Session 目录，Activity Thread 不等于 Native Session。

## 当前 RightSidebar
`src/renderer/src/components/right-sidebar/index.tsx`：App Shell 级区域，管理 open/close、width、resize、Activity Bar 和 tab routing。

`right-sidebar-panel-content.tsx`：Explorer、Source Control、Checks、Ports、Vault、Workspaces/attached worktrees、PR Checks、Plugin Panel。

`use-right-sidebar-activity-items.ts`：面板可见性受 activeWorktree、folder workspace、repo kind、SSH Host 和插件状态影响；不同面板依赖不同 workspace/host context。

**结论：** 保留面板功能、Activity Bar、宽度、内部导航、lazy-load 和状态管理；逐步分离面板渲染内容与宿主容器，研究 Standalone Tab 与 Workspace Pane 两种 Host。当前 RightSidebar 不是通用 SidePanel Instance 系统。

## 目标映射
| Porpita 目标 | Orca 现有实现 | 处理 |
|---|---|---|
| Top-level Tab | `#titlebar-tabs` + existing workspace tabs | 复用挂载点，重新确认顶层对象模型 |
| Workspace | Worktree / App Workspace / Pane Layout | 不等同；建立 Porpita 用户布局概念 |
| Pane / Split | tabs slice、layout tree、drop/split actions | 优先复用 |
| Session Index | WorktreeList + SidebarAgentsList | 扩展；ActivityThread ≠ Native Session |
| Native Session View | Native Chat / Terminal panes | 直接复用 |
| SidePanel Definition | `RightSidebarPanelContent` | 提取或适配 |
| SidePanel Instance | 当前 active right-sidebar tab 与 App Shell 状态 | 新增轻量实例/容器归属能力 |
| Standalone SidePanel | 无已确认通用独立工作对象模型 | 新增呈现宿主 |
| Workspace 内 SidePanel Pane | 现有 Pane 内容类型能否扩展待核实 | UI SPEC 确认最小扩展 |
| Tab Group | `groupsByWorktree` | 复用交互，重新定义作用域/归属 |
| 跨 Project Multi-Session | 当前 Pane/Layout 以 worktree 组织 | 主要结构差异 |

## UI SPEC 必须从源码回答
1. `Tab.contentType` 能否扩展承载 SidePanel，而不破坏 content lifecycle？
2. `unifiedTabsByWorktree` / `layoutByWorktree` 是否能抽取为 workspace-scoped layout owner，还是需独立 layout model？
3. Pane Native Session 与 Worktree/Host context 如何绑定？跨 Worktree Pane 是否支持？
4. `#titlebar-tabs` 由哪些组件挂载？拖动、溢出、固定、关闭和恢复由谁管理？
5. RightSidebar 各面板哪些能脱离 activeWorktree？哪些必须固定 Repo/Host/Worktree？
6. PluginPanel bridge/remount 生命周期是否允许作为独立 Instance？
7. `workspace-board`、`floating-workspace-panel` 与 `WorkspaceTabs` 的边界是什么？名称含 workspace 的对象是否实际是 Worktree 或 pane owner？
8. SidePanel 移动时哪些状态保留，哪些面板需要重挂载？
9. 当前关闭 Tab 是否触发 Terminal/editor retirement？新 Workspace close 必须避免沿用错误语义。
10. 多窗口与 session restoration 对顶层 Tab / Workspace layout 有何限制？

Codex 应以源码和运行时回放回答，不要仅根据类型名称推断。
