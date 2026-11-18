# 第十六轮 · 按位置筛选会话，按项目分组

位置筛选跟随用户要继续的工作范围。候选为常驻多按钮与一个单选菜单。采用 Orca 侧栏的下拉结构，在同一个菜单内明确区分位置与分组。触发器显示当前范围，筛选时一直保留搜索历史入口。项目按来源 ID 分组，用当前项目名作标题。 [VS Code 会话分组](https://code.visualstudio.com/docs/agents/run/sessions/organize-sessions#pin-and-group-sessions) · [实际菜单](evidence/iteration-15-17-windows-zh/i16-project-menu.png)

| 操作 | 规则 |
| --- | --- |
| 所有本地工作树 | 初次进入使用此范围，显示已打开且归属明确的本机 Chat。 |
| 当前工作树 | 仅包含工作台当前选中的本机 Worktree。切换工作树时重新取值。 |
| 已打开的工作空间 | 只显示已加入打开的 Workspace 的 Chat，所有 Tab Group 一并纳入。命中行继续显示具体打开位置。 |
| 最近 / 项目 | 「最近」读取工作台 Tab 最近激活时间，缺失时用创建时间。同一排序作为项目分组内的初始顺序。输入时沿用 `Command` 的匹配排序。 |
| 回到目录 | 查询、位置筛选与分组跟随当前应用运行。重复打开菜单时读到现选值，Escape 把焦点交回菜单按钮。 |

短窗试验中，完整展开的全局导航占掉大部分目录高度，640×520 一度只能看到第一行的上边缘。最终设计把筛选与历史并排放置，按 `max(80px, 窗口高度 − 440px)` 限制顶部全局导航的最大高度，超出部分保有纵向滚动。搜索和列表各有固定边界，列表用剩余空间。640×520 检查至少两个完整结果可见，600×400 检查导航仍能独立滚动。 [原试验](evidence/iteration-15-17-shape/i16-scoped-projects.png) · [最终布局](evidence/iteration-15-17-windows/i16-scoped-projects.png)

菜单复用共享 Radix 开合反馈，入场 150ms 淡入、轻微缩放与方向位移，缓动沿用原组件。减少动态时关闭菜单出入动画；范围更新、行重排与空态即时替换。源码位于 `SessionIndexOptionsMenu.tsx`、`session-index-preferences.ts`、`SidebarNav.tsx` 与 `ui/dropdown-menu.tsx`。

## 验收

在同一侧栏回放当前工作树、已打开的 Workspace、按真实项目分组、无命中、菜单键盘打开和 Esc 回焦。以窗口内菜单、有效选项、实际结果、历史入口与文本边界为判据。目录设置的跨应用重启与大列表性能各有后续验收。 [筛选结果](evidence/iteration-15-17-windows-zh/i16-scoped-projects.png) · [空态](evidence/iteration-15-17-windows-zh/i16-no-results.png) · [回放](evidence/iteration-15-17-windows-zh/run.json)
