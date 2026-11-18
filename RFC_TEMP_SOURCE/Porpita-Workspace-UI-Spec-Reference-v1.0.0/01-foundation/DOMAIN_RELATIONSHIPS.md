# 领域对象与关系基线

## Native Session 不是 Identity
一个 Identity 可以拥有多个 Native Session。每个 Session 有独立历史、运行状态、Harness、机器和生命周期。相同 Identity 不得导致多个 Session 合并。

| 关系 | 基数/约束 | 说明 |
|---|---|---|
| Project → Session | 0..N | Session 可独立存在 |
| Route → Session | 0..N | Route 可关联多个 Session |
| Identity → Session | 0..N | 同一身份可拥有多个 Session |
| Session → Identity | 通常 1 个主要身份 | 关联需可验证 |
| Session → Harness | 1 个主要 Harness | 记录实际承载环境 |
| Session → Machine/Host | 1 个当前主要位置 | 位置可随迁移/恢复变化 |
| Route → Project | 1 | Route 隶属一个 Project |

## 主要归属与额外关联
初代建议一个 Session 最多有一个主要 Project 和一个主要 Route，也允许无归属。额外协作关联必须显式建立。UI 多维分组不改变底层授权；出现在多个视图不意味着跨 Project 权限共享。

## Session 标识
区分稳定 Porpita Session reference（列表、收藏、Workspace 引用）、Native Session reference（Harness 原生 ID）和 Session generation（运行实例/重绑定代次）。进程重启不应自动产生新的用户可见 Session；同一 Identity 新建 Native Session 也不得被合并。

## ACS Conversation 与 Native Session
Native Session 记录 Harness 原生交互、工具调用、审批和流式输出。ACS Conversation 记录通信参与者之间的消息、显式回复、附件和通信状态。一个 Native Session 可关联多条 ACS Conversation；多个 Session 不共享 Native transcript。UI 可以建立可追溯关联，但不能把 ACS 消息伪装成 Native Chat 消息，也不能把 Native 输出自动伪装成 ACS 回复。

## Workspace 与 Project
Workspace 是用户工作布局，不是 Project 的 UI 别名。一个 Project 可以有多个 Workspace；Workspace 可以包含不同 Project 的 Session。Workspace 不拥有 Session 执行生命周期。

## SidePanel Definition 与 Instance
Definition 是 Explorer、Source Control、Checks、Ports、Vault、Plugin Panel 等功能类型。Instance 是实际打开的面板实例，具有 scope、host/project/workspace context、内部 Tab 状态和 view state。同一类型可有多个 Instance。初代同一 Instance 同一时刻只在一个位置交互式呈现。

## Top-level Tab 与 Tab Group
Top-level Tab 类型为 Workspace 或 Standalone SidePanel。Tab Group 只组织顶层 Tab，不管理 Workspace 内 Pane，也不管理 SidePanel 内部 Tab。
