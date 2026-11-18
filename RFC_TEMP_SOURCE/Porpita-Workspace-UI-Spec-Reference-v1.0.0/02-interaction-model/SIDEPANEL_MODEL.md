# SidePanel 独立工作对象与嵌入模型

## 产品定义
SidePanel 是独立功能性工作对象，不是 Native Session，也不是 ACS Conversation。它保留 Orca 现有功能和内部交互，可独立作为 Top-level Tab 打开，也可作为 SidePanel Pane 嵌入 Workspace。

## 当前 Orca 真实边界
当前 RightSidebar 是 App Shell 级 docked panel：具有开关、宽度、resize、Activity Bar、active tab routing 和 lazy-loaded panel content。包含 Explorer、Source Control、Checks、Ports、Vault、Workspaces、PR Checks、Plugin Panels。多种面板依赖 activeWorktree/workspace/Host 上下文。因此它不是已存在的通用、可独立挂载任意 Pane 的 Panel Instance 系统。独立 Tab / Workspace Pane 是扩展，不是简单配置。

## Definition 与 Instance
Definition 定义功能类型和渲染/能力要求。Instance 是实际打开的面板实例，可能包含稳定 ID、type、scope、host/project/workspace context、内部 Tab 选择、view state、presentation（standalone/embedded）和当前容器引用。不是所有 Definition 都适合任意 Scope。

## Scope（推荐）
- Global：不依赖项目或 Host。
- Project：固定 Project。
- Workspace：固定 Porpita Workspace。
- Host：固定 Harness Host / Machine。
- Session：显式绑定 Native Session。
面板可支持一种或多种 Scope，不强制全部支持。

## 上下文规则
固定 Scope 的 Panel 不随焦点 Session 自动切换。可选 Follow Focus 是用户明确选择的偏好。Explorer/Source Control 等依赖 Worktree 的面板必须明确绑定 Host/Worktree/Repo。多 Project Workspace 中焦点变化不得无提示改变面板数据来源。上下文不满足时显示选择上下文的空态，不隐式回退。

## 实例移动与复用
Standalone 移入 Workspace：移动同一 Instance，关闭原 Standalone Tab。Workspace 移出：移动同一 Instance，生成/激活 Standalone Tab。同一 Definition 再次打开时按 Scope 决定复用或新建。初代同一 Instance 只允许一个交互式容器。不同 Workspace/Host 的同类型 Panel 可以是不同 Instance。移动不得丢失内部 Tab 和视图状态。

## 内部 Tab
SidePanel 内部 Tab 独立于 Top-level Tab Group。Source Control 的 Changes/History/Branches 不进入全局 Tab Bar。

## 关闭与删除
Close 关闭呈现入口；Remove 从 Workspace 布局移除；Destroy 才真正删除 Instance 或持久状态，必须独立明确。Workspace 关闭不自动 Destroy 内嵌 SidePanel。

## UI SPEC 必须逐类核对
Explorer、Source Control、Checks、Ports、Vault、Workspaces、PR Checks、Plugin Panel：是否依赖 activeWorktree、是否依赖 App Shell、是否有内部 Tab、能否独立运行、是否支持多实例、状态存在哪里、移动宿主时如何保留状态。初代允许部分面板只保留 Docked 模式。
