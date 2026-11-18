# Codex UI SPEC Brief：Porpita Workspace / Tab / SidePanel

## 本轮目标
基于真实 Porpita / Orca 客户端，完成 Workspace、Top-level Tab、Tab Group、SidePanel、Session Index 的 UI SPEC 研究、shape、迭代和体验验收，形成可供用户确认的完整参考结论。

**本轮不是直接实现所有 UI 改造。** 先产出可回放、可比较、可审查的 UI SPEC，再据此形成实现方案。

## 已确定结论（不要重新开放讨论）
- Porpita 是独立产品，Orca 是客户端与运行时上游基线。
- 保留 Orca 原生视觉语言、Native Chat、工具、审批、终端、Diff。
- Session 是用户直接访问的基本工作对象。
- Project / Route / Identity / Harness / Machine 是关联维度，不形成固定会话树。
- Workspace 是用户工作布局，不等于 Project。
- 一个 Top-level Tab 对应 Workspace 或 Standalone SidePanel。
- Workspace 可组合多个 Session 与 SidePanel。
- SidePanel 是独立功能性工作对象，可独立打开，也可嵌入 Workspace。
- SidePanel 内部 Tab 独立于顶层 Tab Group。
- Sidebar / Session Index 负责 Session 发现；Top-level Tab Bar 负责工作对象切换；Workspace Main Area 负责组合呈现。
- 关闭 Workspace 不结束 Native Session；移除 Pane 不销毁对象。
- ACS Conversation 与 Native Session 保持不同实体和数据来源。

## UI SPEC 研究工作
### A. Workspace / Pane / Session
观察 Orca 当前 Tab/Pane/Split/layout tree；对比单 Session、多 Session、跨 Worktree、跨 Project；研究拖放、Split direction、pane sizing、focus、maximize/restore；研究 Session 在不同 Workspace 间的打开、复用、移动、关闭和恢复；输出最小完整 Workspace UX 定义。

### B. SidePanel
逐一回放 Explorer、Source Control、Checks、Ports、Vault、Workspaces、PR Checks、Plugin Panel；确认每个面板的 Scope、上下文依赖、内部 Tab、实例状态和卸载行为；确认哪些可 Standalone、哪些可 Embedded、哪些初代只能 Docked；输出 Definition/Instance/Host 的最小定义。

### C. Top-level Tabs / Groups
实际观察 Titlebar tab strip 的布局、拖动、固定、关闭、overflow、快捷键和多窗口行为；比较 Group Selector、分组式 Tab Strip、折叠分组和 Overflow；确认自动分组推荐与用户手动调整优先级；输出窄窗口和大量工作对象下的交互 SPEC。

### D. Session Index / Sidebar
研究现有 Workspaces / Agents 视图；证明 Activity Thread 与 Native Session 的数据差异；设计 All / Active / Needs Attention / Favorites / Unassigned；研究 Group By 与多条件 Filter；设计点击、右键、拖放到当前 Pane / 新 Workspace。

### E. 端到端体验回放
1. 启动并恢复上次顶层工作对象。
2. 从 Session Index 找到 Root Session。
3. 在当前 Workspace 打开 Root。
4. 将 Route Manager 拖入新 Split。
5. 将 Explorer / Source Control 作为 SidePanel 加入。
6. 新建跨 Project Workspace 并加入另一个 Session。
7. 创建/切换 Tab Group。
8. 将独立 SidePanel 移入 Workspace，再移出。
9. 最大化某 Pane 后恢复原布局。
10. 关闭 Workspace、重开应用，确认 Session 与布局生命周期分离。

## 必须区分的数据权威
- Native execution：Harness / Orca。
- ACS communication：ACS Core。
- Workspace / Tab / Pane / SidePanel presentation：Porpita UI state。
- Session association projection：Porpita 组合 ACS + Host 的结果。

不能把所有状态压成一个 status，也不能让 UI 本地布局状态写回 ACS Project / Route / Identity 权威。

## 最终 UI SPEC 交付物
1. `UI_SPEC_SUMMARY.md`
2. `OBJECT_MODEL.md`
3. `INTERACTION_SPEC.md`
4. `ORCA_REUSE_MAP.md`
5. `SIDEPANEL_CAPABILITY_MATRIX.md`
6. `SESSION_INDEX_SPEC.md`
7. `TAB_GROUP_SPEC.md`
8. `WORKSPACE_LAYOUT_SPEC.md`
9. `PLAYBACK_SCENARIOS.md`
10. `OPEN_QUESTIONS.md`
11. `DECISION_LOG.md`

## 验收标准
- 结论追溯到真实 Orca/Porpita 行为、用户场景或明确产品原则。
- 不混淆 Worktree、Native Session、ACS Conversation、Workspace。
- 同一 Native Session 不因分组/多视图产生重复身份。
- 不同 Project / Host / Worktree 的 Session 保持独立上下文。
- SidePanel 不因焦点 Session 改变而意外切换上下文。
- Close / Remove / Destroy 语义明确。
- Tab Group 不持续覆盖用户手动分组。
- 关键场景通过录制、截图或交互回放验证，不只提供静态示意。
- 优先复用 Orca 已有组件与交互；任何重构说明现有机制不能满足的具体原因。
- 不以新增大量状态机、抽象层或防御性校验作为 UI SPEC 成果。
- 本轮先交付设计结论，未经确认不启动大规模 UI 实现。
