# Session Index / Sidebar 与导航交互基线

## Sidebar 职责
Sidebar 的核心内容是 Session Index：所有 Porpita 当前有权访问、可识别的 Native Session 的统一发现入口。负责搜索、筛选、分组、轻量身份/运行信息、进入 Session、将 Session 加入 Workspace。它不负责顶层 Workspace Tabs、Tab Groups、SidePanel 内部 Tab 或隐式结束 Session。

## Session 条目
推荐最多三层：Session 名称；Identity/Role + Harness；轻量活动状态、未读、待处理提示。Project/Route 可由当前分组标题表达。Machine 优先放详情/tooltip。

状态来源必须区分 Native execution（Harness/Host）、ACS communication（message/unread/delivery）、Host availability（connected/disconnected/unknown）。不得压成单一模糊状态，也不得把 Native ACK 表示为 Agent 已处理。

## 分组与筛选
Group By 一次选择一个主要维度：None/Recent、Project、Route、Identity、Harness、Machine。Filter 可组合多个条件，例如 Project=Porpita AND Harness=Codex AND Status=Working。快捷视图可包括 All、Active、Needs Attention、Favorites、Unassigned。这些是过滤视图，不是新实体。

## 同一 Session 在不同视图中的唯一性
同一 Session 可在 Project、Route、Identity 或 Harness 视图中出现，但必须引用同一个稳定 Session reference。切换视图不创建新会话、不改变焦点、不丢失 Workspace 状态。

## 点击和拖放
推荐默认：单击未打开 Session 在当前 Workspace 焦点 Pane 打开；无 Workspace 时创建单 Session Workspace。已在当前 Workspace 则聚焦。已在其他 Workspace 则激活原 Workspace 并聚焦。拖到 Pane 中心按宿主规则替换/放入；拖到边缘创建 Split。明确命令 Open in New Workspace 创建新 Workspace。右键菜单提供 Open in New Pane / New Workspace / Reveal Existing Workspace。

## Sidebar 与当前 Workspace
Sidebar 默认保持全局 Session Index，不随 Workspace 切换自动改变 Project Filter。提供快捷过滤 “In Current Workspace”。条目轻量显示当前 Workspace 已打开、其他 Workspace 已打开或未打开；不默认展开所有所属 Workspace。
