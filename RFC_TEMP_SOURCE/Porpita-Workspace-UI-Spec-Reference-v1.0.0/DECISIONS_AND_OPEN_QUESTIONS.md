# 决策状态与开放问题

## 已确定（Confirmed）
1. Porpita 是独立产品，Orca 是上游 UI / 桌面运行时基线。
2. 保留 Orca 原生视觉与核心 Chat / 工具 / 审批 / Terminal / Diff 体验。
3. Session 是用户访问和交互的基本工作对象。
4. Project、Route、Identity、Harness、Machine 是关联维度，不是固定 Session 父子树。
5. 一个 Identity 可有多个独立 Native Session。
6. Native Session 与 ACS Conversation 不同。
7. Workspace 是用户工作布局，不等于 Project。
8. 一个 Top-level Tab 对应 Workspace 或 Standalone SidePanel。
9. Workspace 可组合多个 Session 与 SidePanel。
10. SidePanel 保留独立功能语义和内部 Tab。
11. SidePanel 可独立打开，也可嵌入 Workspace。
12. Sidebar / Session Index 负责发现 Session；Tab Bar 负责切换顶层工作对象；Workspace 负责组合工作对象。

## 推荐默认（Recommended）
1. 一个 Session 初代只允许在一个 Workspace 中交互式呈现。
2. Session 已在其他 Workspace 打开时，默认激活原 Workspace。
3. Sidebar 单击 Session 在当前 Workspace 焦点 Pane 打开；没有 Workspace 时创建单 Session Workspace。
4. Open in New Workspace 是明确命令。
5. SidePanel Standalone ↔ Embedded 默认移动同一 Instance。
6. 同一 SidePanel Instance 初代只在一个位置交互式呈现。
7. 自动 Tab Group 只在创建时提供推荐，用户手动调整后不自动覆盖。
8. 多 Project Workspace 默认进入 General 或用户当前选择的 Group。
9. 关闭 Workspace 不结束 Native Session；移除 Pane 不销毁对象。
10. SidePanel Scope 默认固定，不自动跟随焦点 Session。

## 待 UI SPEC 研究（Open）
1. Tab Group 是 Group Selector 还是同一横向 Tab Strip 分组呈现？
2. 现有 Orca Tabs 是 per-worktree 内容 Tab；如何最小化抽取为 Porpita top-level Workspace Tab？
3. 跨 Worktree / Project Session 能否复用当前 Pane Tree？是否需要独立 Layout Owner？
4. Session 单击的最终默认：替换焦点 Pane、打开新 Tab 还是复用/激活？
5. SidePanel 哪些类型具备 Standalone / Embedded 资格？
6. Explorer / Source Control 等依赖 activeWorktree 的面板如何固定 Scope？
7. Plugin Panel 能否安全重挂载到不同 Host？
8. 同一 SidePanel Definition 多 Instance 的状态隔离策略。
9. Tab Group 在窄窗口和大量 Tab 下的最佳视觉形态。
10. 多窗口下 Workspace / Session 的唯一性与恢复策略。
11. Workspace 默认命名、重命名与 Project affinity 提示。
12. Session Index 的状态摘要、未读归属和 Needs Attention 规则。

## 明确不做（Non-goals）
- 不把 ACS Project / Route 变成固定导航树。
- 不把每个 Session 都变成顶层 Tab。
- 不把 SidePanel 变成 Session 或 Conversation。
- 不把 Orca 原生 Chat transcript 迁入 ACS。
- 不重写 Orca Pane / Split 引擎，除非源码回放证明无法扩展。
- 不把 Workspace 强制绑定 Project。
- 不允许布局变化修改 ACS 权限或通信身份。
- 不以静态 mockup 替代真实 Orca UI 行为研究。
