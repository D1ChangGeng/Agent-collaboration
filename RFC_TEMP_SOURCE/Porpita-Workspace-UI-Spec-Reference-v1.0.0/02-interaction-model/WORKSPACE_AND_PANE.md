# Workspace 与 Pane 交互基线

## 定义
Workspace 是用户创建、命名、保存和恢复的工作上下文，包含 Pane layout、Pane 内容引用、焦点和呈现状态。它不是 Project、Native Session 或 ACS Conversation。

## 组成
Workspace 可包含一个或多个 Native Session Pane、零个或多个 SidePanel Pane、Split/nested Split，以及每个 Pane 的尺寸、展开/收起和焦点状态。初代至少支持单 Session、多 Session、Session + SidePanel、跨 Project/Route/Harness 组合。

## 生命周期边界
- 关闭 Workspace Tab：关闭工作布局，不结束 Native Session。
- 从 Workspace 移除 Session：只移除布局引用，Session 仍在 Session Index。
- 结束 Native Session：独立、明确的 Harness 操作。
- 删除 Workspace：删除布局对象，不自动删除 Session、Project 或 SidePanel Definition。

## Session 打开规则（推荐默认）
| 用户动作 | 推荐行为 |
|---|---|
| 单击未打开 Session | 在当前 Workspace 焦点 Pane 打开；若无 Workspace，创建单 Session Workspace |
| 单击当前 Workspace 已有 Session | 聚焦对应 Pane |
| 单击其他 Workspace 已有 Session | 激活其 Workspace 并聚焦，不创建重复实例 |
| Open in New Workspace | 创建仅包含该 Session 的 Workspace |
| Open in New Pane | 在当前 Workspace 新建 Pane 并加入 Session |
| 拖入 Pane 中心 | 替换该 Pane 内容，遵循宿主未保存状态规则 |
| 拖入 Pane 边缘 | 按方向创建 Split 并加入 Session |
| 从一个 Workspace 移至另一个 | 初代默认移动；原 Workspace 保留合理空态或收敛布局 |

## 多 Workspace
初代同一个 Native Session 同一时刻只存在于一个可交互 Pane，避免多个输入框竞争同一原生输入通道。未来可考虑只读镜像。

## Pane 与焦点
每个 Pane 是真实 Session 或 SidePanel Instance，不是任务卡片。任意时刻有明确焦点 Pane；输入、停止、审批、模型操作必须指向明确焦点对象。关闭 Pane 不等于结束 Session。最大化/恢复不得丢失布局。Pane 尺寸和 Split ratio 持久化于 Workspace。Session 不可用时显示可恢复占位状态，不破坏布局。

## 跨 Project / Worktree
Workspace 可以跨 Project 组合 Session，但每个 Session 保持自己的 Worktree/Host 所有权。不能让多个 Pane 因处于同一 Porpita Workspace 就共享错误的文件、终端或权限上下文。Codex UI SPEC 应确认 Orca 现有 Pane 模型是否支持跨 Worktree 组合。

## 布局复杂度
优先复用 Orca Pane Tree / Split。不要重新实现布局引擎。默认布局保持简单，复杂嵌套 Split 由用户主动操作产生。
