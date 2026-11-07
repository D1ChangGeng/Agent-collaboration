# 02｜目标架构和数据所有权

## 分层

Agent / 普通客户端 → 既有 MCP 或新 Client HTTP → ACS Communication Service → 现有 Authority/PostgreSQL + Outbox → Receiver coordinator → Harness Adapter → 原生 Harness。

Orca 集成层同时访问 ACS Client API 与 Orca Native View Provider。它组合“ACS 通信行”和“宿主原生执行行”，保留来源，不把两条数据流相互伪装。

## 所有权表

| 数据/能力 | 唯一权威 | 其他层允许行为 |
|---|---|---|
| 可信 actor、Slot/Client 地址、Project/Route/Grant | ACS 现有授权域 | 展示/受权配置，不能由 UI 传入作者 |
| 原始 Message、reply_to、收发双方、提交顺序 | ACS Authority | 只读投影/索引，不重写原文 |
| 技术投递/恢复操作与 Native 接纳证据 | ACS operation ledger + 接收端证据 | Adapter 报告证据；Core 接纳/投影 |
| 原生 Session、turn/tool/approval/transcript | Harness 或 Orca session host | scoped reference、按需代理/展示；不影响消息因果 |
| UI 阅读位置、草稿、收藏/静音 | 对应主体的个人状态域 | 设备同步；不是对端已读或模型消费 |
| Task/Run/Gate/工作区/Git Diff | Orca 或上层 Orchestrator | reference/delegation；不成为发送条件 |

## 生命周期分离

`address` 持续存在；`binding_id` 指向获授权接收位置；`binding_epoch` 仅在接收绑定改变时递增；`provider_generation` 标记原生运行实例；`native_session_ref` 只是 Provider 的 opaque reference；`message_handle` 与以上实例生命周期独立。

显示名、角色标签或 UI tab ID 不得作为可信作者。修改显示名不推动 receiving epoch。历史 receipt 永远保留当时绑定/实例，不在 rebind 后冒充新 Session 的接收证据。

同 Slot 多接收端：沿用显式 endpoint 选择或已配置的唯一合法目标。无法唯一解析时消息可留 Inbox，但激活为 `receiver_selection_required`，不能广播唤醒多个 Session。不同 Slot 共享 principal 不代表同一发件人。

## 运行边界

观察路径无副作用：list/read/discover 不启动、恢复或唤醒。发送 activation=invoke 与明确受权恢复才可导致 Native 副作用。UI subscription 不替代维护器，关闭 UI 不影响已提交消息。

Adapter 只完成通信必需的最小状态观察、接收、必要准备/恢复与证据核对。无需持续采集完整推理、工具结果和终态；宿主事件丰富时可只读转给 Native View Provider，不能投影为 ACS reply。

后台组件沿用已装服务及默认 MCP/HTTP 维护路径；可将重复维护者收敛为具有租约的竞争 worker，但必须支持幂等、fencing、故障恢复和安装生命周期。不能引入只有开发启动命令才存在的隐藏服务依赖。

## 上层编排

Orchestrator 可以订阅 ACS 事件并在自身领域解释完成通知。ACS 对普通消息只做身份/关联/权限/格式检查。`worker_done` 字符串不产生 Core 特权；Native Runtime completed 也不能被 Core 自动转为完成消息。可选 task reference 仅 opaque external metadata，不作为路由或授权依据。

## 多主机

跨机器保持现有 authority/node/receiver trust。Relay 仅持久运输 sealed envelope 与签名 receipt；不能改变 sender、recipient、binding epoch、operation ID。承认通信延迟/断线，拒绝假定全局墙钟一致。离线不能承诺及时消费；连通恢复并满足权限/能力/资源条件后按有界公平调度继续。
