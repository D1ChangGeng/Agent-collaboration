# 04｜投递状态、事务和幂等

## 不用一条线性状态掩盖事实

每条 message 持久记录 accepted/inbox 事实；每个 native input operation 记录自己的 state；每项 receipt 带 source/evidence/绑定代次；显式 reply 是独立 Message 和关系索引。可能出现：`native=unknown` 但 `response.present=true`。该回复满足 wait，但不能倒推某次未知 transport ACK 成功。

`provider_consumed` 仅在原生接口提供可关联的输入消费事实时记录，语义是“Provider 接纳并将特定输入交给处理阶段”，不是模型理解或业务完成。没有此能力为 `unobservable`，不是 false 也不是成功。

## 状态机

`queued → deferred/preparing/submitting`；`preparing → queued/deferred/definitively_rejected/unknown/superseded`；`submitting → accepted/definitively_rejected/unknown`；`unknown → accepted/definitively_rejected` 只能来自 reconcile 证据；已确定拒绝且可重试 → queued。详细合法边在 contracts/delivery-transitions.json。

`cancelled_before_submit` 只用于确认尚无原生副作用的发送操作。停止 wait、归档 conversation、标已读、删除草稿都不能取消接收方的工作。取消消息激活与 stop native turn 是不同命令，本轮不新增通用任务取消器。

## 事务边界

T1：授权锁/现有 project serialisation → dedup 查询 → 提交原包、索引、reply 关系、Outbox、client event intent → commit → ACK。重复请求返回同 message，不二次通知。
T2：claim due operation，获得 per-Slot fence 与短 lease；保存选择的 binding epoch 和能力证据。绝不持有 DB 写锁等待 Native 网络请求。
T3：Receiver 验证签名/权限/代次，原子领取 operation，持久写 handoff_intent；之后才调用原生。
T4：返回 Native 结果/receipt，按相同 operation 原子记录；若无确定结果则 unknown。崩溃窗口必须可从 Node journal 和 Provider 查询恢复。
T5：Outbox event 可至少一次投递；客户端按 event_id/revision 去重。事件通知失败不撤回 T1。

## 原生 exactly-once 的可实现边界

如果 Provider 对稳定 idempotency key 有明确跨重连去重承诺，可在原去重域内重放同 operation。若 Provider 只有“提交”无查询/防重，持久 handoff_intent 后崩溃可能停在 unknown；此时安全优先，不重复提交。禁止把 CAS lease、数据库唯一键或“只调用一次本地函数”当作跨故障 exactly-once 证明。

新 Session/新的主机往往意味着新的原生去重域；不能携同 operation ID 就宣称天然去重。恢复需旧输入确定未接纳、或能够验证旧接收端不可再执行且业务授权允许重新提交；即便旧进程已退出也不能否定此前输入已执行。未能排除先前副作用必须保留 unknown。

## 顺序与公平

默认每个稳定收件地址串行 Native admission，保持对该收件人的已提交消息顺序；跨收件人并发保留现有默认上限并配置化。消息过期/不可达可停住激活，但不删除 Inbox。批量只合并连续可交付段，提交前冻结精确 message IDs；一批不得跨过 wait reply、审批或人工输入的控制边界。

大正文采用“可信 envelope + message ref + 拉取”或分块供给。超限不得截断后声称完整送达。收件人应能用 read_message 取得原文。附件准备不允许把 local path 当远端可读路径。

## 客户端重试

HTTP 使用 Idempotency-Key，映射既有 client_request_id。客户端在断线后先查询 operation/message；重复键内容 hash 不同返回 409。wait timeout 不重发。`request not found` 不是无副作用证明，尤其遇到已清理日志/不同 authority incarnation，必须先核对原运行域。
