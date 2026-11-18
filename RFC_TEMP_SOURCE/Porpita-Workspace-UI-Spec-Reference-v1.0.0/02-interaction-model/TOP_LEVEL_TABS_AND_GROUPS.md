# Top-level Tab 与 Tab Group 交互基线

## 顶层 Tab
一个 Top-level Tab 对应一个独立打开的工作对象：Workspace Tab 或 Standalone SidePanel Tab。Session 不直接成为顶层 Tab，而通过 Workspace 进入工作区域。SidePanel 可以独立成为顶层工作对象。

## 三种 Tab 不可混淆
1. Top-level Tab：Workspace / Standalone SidePanel。
2. Workspace Pane 内部的 Session / SidePanel 内容切换（若宿主采用 Tab 形式）。
3. SidePanel 自己的 Internal Tabs，例如 Changes / History。
它们可以复用视觉组件，但数据模型、关闭语义和导航职责不同。

## Workspace Tab 元信息
建议包含稳定 workspace_id、用户可编辑名称、可选图标/颜色、所属 Tab Group、固定状态、最近访问时间、激活状态和可恢复状态。名称优先由用户维护，不随第一个 Session 改变而频繁变化。

## Tab Group
Tab Group 是顶层工作对象的用户组织容器，不是 Project 或 Route 的数据模型。用户可创建、重命名、折叠、固定、移动 Tab。新 Workspace 创建时可根据主要 Project affinity 推荐默认 Group；无 Project 或跨 Project Workspace 默认 General 或沿用用户明确选择。用户手动调整后，系统不得因 Session 关联变化自动重排。删除 Group 时移动其 Tab，不关闭工作对象。Standalone SidePanel 不强制绑定 Project。

## 自动分组原则
自动分组是推荐默认值，不是持续重分类。跨 Project Workspace 不强制归入某一 Project。Workspace 内容变化不覆盖用户分组，不改变 Project/Route 关联或权限。

## Tab Bar 视觉问题待 UI SPEC 决定
比较 Group Selector + 当前组 Tabs、分组式 Tab Strip、可折叠 Group Strip、横向滚动和 Overflow。研究窄窗口、大量 Tab、长名称、未读/活动状态。不要预先锁定第二行导航；优先复用 Orca 原生 titlebar/tab strip。

## 关闭行为
关闭 Workspace Tab 不结束 Session；关闭 Standalone SidePanel Tab 不默认销毁持久状态；删除 Tab Group 不关闭组内 Tab。存在未保存面板状态时复用宿主确认行为。
