# 02｜目标架构：替换通信，不替换成熟执行环境

```text
Porpita Renderer（继承 Orca 布局/Native Chat/Terminal/Editor/Diff）
        │ 既有 preload / typed RPC；少量 communication view model
Porpita Host / daemon（继承 Orca Runtime，唯一原生输入拥有者）
        ├─ 原生会话 / Provider / 工作区 / 工具 / 审批 / 可选工作流
        ├─ Porpita communication integration（薄适配与身份关联）
        │      ├─ 已有 ACS HTTP/SDK → ACS Authority / PostgreSQL
        │      └─ 既有 ACS Receiver backend ↔ Host 原生 input handover
        └─ 模型进程携带自身 ACS MCP 可信绑定
ACS Core 可托管本地，也可为已有远端服务；不依赖 Porpita UI 存活
```

## 四个职责边界

**ACS Core**：Agent 身份、组织/授权、联系人、Message/reply_to、Inbox/历史、投递事实和客户端服务。沿用单一权威，不移植 Task/Gate。

**Porpita Host**：原生会话、输入队列、进程、工具、审批、Transcript、工作区、原生恢复。已有原生 journal 是输入和执行事实；它不是需要删除的“第二通信内核”。

**Integration**：把稳定 ACS 地址关联到宿主会话，映射消息 API/事件/已有 CLI，完成受信接收。保持薄，不另造新业务协议或万能 Adapter 框架。

**Renderer**：复用既有组件与 stores，呈现两种来源。消息投递成功不是模型完成；原生输出不是自动的 ACS reply。用户能追到来源，但默认不展示内部 operation/epoch。

## 数据所有权

| 数据 | 权威 | 其他层允许持有 |
|---|---|---|
| ACS Message 正文、作者、回复 | ACS | 有权限的渲染缓存、宿主实际输入副本 |
| 当前联系人/Slot 与 Native Session 关联 | ACS NativeLink + 宿主当前 session metadata | 可重建映射，不再独立发明身份 |
| 历史 Message 对应原生 input/turn | 原 ACS 回执 + Host journal，SourceLink | 引用，不按同名或文本猜测 |
| Transcript、tools、Diff、approval | Host/Harness | 当前受权视图，不存为 ACS 消息权威 |
| 用户未读、草稿、偏好 | ACS 对应私人资源 | SDK reducer/本地暂存 |
| Run/Task/Dispatch/Gate | 保留的宿主工作流模块 | ACS 只承载自然消息，不解释其状态 |
| UI 布局、窗口、worktree、模型设置 | 继承宿主设置 | 不迁入 ACS |

## 运行模型

本地默认：UI 通过现有 IPC 调宿主，宿主调用托管本地 ACS；模型用 MCP 可信上下文访问同一 Core。远端默认：UI 仍用本地宿主连接已有 ACS，接收操作在会话真正所在主机执行，不在本地主机假定远端文件或进程存在。

Electron main/preload/renderer 的边界沿用上游。凭据保留在既有安全存储或受限服务配置；renderer 只收到自己的视图和允许动作。无需新增签名体系，复用已有 ACS/OAuth/Receiver 绑定及宿主连接能力。

## 原位替换完成判据

正常产品中的 A2A 发送、回复、查询、唤醒和远端转递均以 ACS 为通信事实来源。旧 orchestration 消息表可以保留为只读历史或短期迁移输入，不能继续承接新消息。宿主原生输入队列、执行账本及 Task 数据可继续运行；这是职责不同，不是双通信权威。

Core 不可达时：原生用户对 Agent 的工作可按上游继续；跨 Agent 通信显示暂不可用/待恢复，不回落旧消息存储。不要为了“看起来可用”创建临时无权威消息。
