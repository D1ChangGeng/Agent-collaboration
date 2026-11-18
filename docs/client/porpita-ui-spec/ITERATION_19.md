# 第十九轮 · 读取会话运行状态与协作连接

从目录扫一眼某条 Chat 的原生运行状态，需要处理时打开该会话。协作状态在同一区域可进入，连接和回执继续由原协作界面表达。

## 设计与采用

Porpita 的既有 Activity 与 Vault 使用紧凑状态符号。VS Code 在同一列表中把运行和需要处理作为不同阅读任务。目录保留第十五轮的原名称、来源和目标，将 Orca 的 `AgentStateDot` 放在标题行的附加位置。它复用运行反馈、等待形状、无更新标识和减少动态处理。另一个候选是增设一整列状态文字。当前目录宽度更适合保留标题和 Host 阅读路径，符号配合无障碍标签、原生 Chat 中的可执行提示识别。 [Porpita Activity](evidence/current-source/35-activity.png) · [VS Code Inbox 状态](https://code.visualstudio.com/docs/agents/run/sessions/organize-sessions#triage-sessions-with-inbox-mode)

| 用户要判断的事实 | 权威与呈现 |
| --- | --- |
| Chat 正在运行或等待处理 | 读取原生会话所属 Host 的状态流，同时匹配工作树、会话和 Harness。使用现有工作动效、待处理图标和状态文字标签。待处理动作只在实际 Chat 内。 |
| 尚未开始、空闲或无法确认 | 以实时上报的空闲为准。主机已确认没有对话轮次时省略状态。来源尚未确认时用原无近期更新标记。Host 无联系时单独显示 Host 不可用。 |
| 协作是否可用 | 从目录头进入同一个协作 Dialog。Dialog 标题显示检查中、已连接、未连接或连接需要处理，沿用已有连接检查和项目授权。Esc 回目录原按钮。 |
| 某条协作消息处理到哪一步 | 进入原 Conversation，查看该消息的收件箱、原生输入和回复阶段。可验证的消息来源按原权限定位其真实 Chat。目录当前没有跨 Session 的 ACS 关联数据，消息未读按原项目和对话展示。 |

运行状态由按 Host 分离的 `structured-agent-session-status-feed.ts` 驱动。目录订阅单个会话，使用原 `useSessionFeed` 与 `AgentStateDot`，无需另起 Host 轮询。协作入口复用 `CollaborationButton.tsx` 的同一连接查询与 Dialog。消息源及状态见 `CommunicationSource.tsx`、`DeliverySummary.tsx`。

## 验收范围

使用可重放的本地 Harness 协议夹具驱动真实 Electron、原生 Chat、目录和审批提示。验证同一行从运行到待处理、缩窗及减少动态。协作 Dialog 走实际 IPC，验证无配置连接状态、原入口及返回焦点。受控真实模型、已配置 Core 的当前版本连接恢复、真实消息逐条授权关联与系统读屏各有独立判据。

初用通知卡片可能遮到窄窗的原生审批区。本轮通过实际关闭按钮收起这张卡后检查审批可见性。审批、信任和通知的组合回归仍按 J01/J05/J13 核对。

英语和简中均从轮次运行进入待处理状态，在 820×540 核对原审批组件与目录状态。随后打开实际未配置的协作 Dialog，通过 Escape 回入口确认待处理状态仍存在。 [运行画面](evidence/iteration-19-windows/i19-running.png) · [待处理画面](evidence/iteration-19-windows-zh/i19-needs-attention.png) · [协作画面](evidence/iteration-19-windows-zh/i19-collaboration.png) · [切换连续帧](evidence/iteration-19-windows/running-to-attention/timeline.json)
