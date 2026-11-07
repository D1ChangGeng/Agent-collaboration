# 06｜唤醒、Session 连续性与跨主机恢复

## 唤醒和内容分别管理

每个 Inbox 的 wake intent 以 recipient/binding_epoch/未通知边界去重。消息正文始终独立持久。合并 20 条唤醒不等于合并 20 条 Message。Native 内完整正文与 pointer 两种路径都必须保留原 handle/作者/来源，且不能把 Agent 消息伪装成人类授权。

已有活动 reply wait 能返回对应消息时优先走 ToolResult，避免同一回复再启动一轮 Native。waiter 进程失联后，经过现有 lease 清理恢复 Inbox 正常通知；超时不取消对方任务，不因无回复认定对方失败。

## 恢复类别

1. 同进程连接重连：同 operation 查询状态，不新提交。
2. 同 Session 的 Provider 重连：核验 session lineage、generation 和原生去重域；先 reconcile 未决输入。
3. 进程重启而 Session 可恢复：先 attach/resume，读取 journal/Provider evidence；确认接收身份后继续。
4. 原 Session 不可恢复：权限允许才新建，并显式记录新 epoch。旧未知 operation 不自动迁入新 Session。
5. 原生权限/账号变更：暂停发送，重新验证；不以 owner 管理权限模拟原主体。
6. 跨主机 receiver 更换：原主体与历史保持，enrollment/host/transport trust 重新校验；旧 generation fence 仍生效。

## 最小接入上下文

新的原生会话只注入：当前可信 ACS 地址、Project/Route 责任上下文引用、实际 manager、当前 message handle/作者、如何读全文/回信/查 Inbox 的准确动作。按授权和预算按需展开。不注入整段历史，不复制全部文件，不自行补造工作记忆，也不要求 Worker 发送 worker_done。

## Relay

复用当前 Node/Receiver/Tunnel 拓扑，不因借鉴 Orca 引入一个新的 federation task owner。Relay 保存不可变 envelope、请求摘要和投递证据，限制 frame/队列大小，按连接代次/证书指纹/当前 enrollment 验证对端。断线不清除消息；重连按 operation IDs 调和 ACK。Capability 缓存被 peer fingerprint/epoch/version 变化失效。

## 故障通知

保留现有 ACS system notice：不是 Agent 私信，不进入 reply 关系，不泄露原文。确定通信阻碍可发给实际 manager；busy 延迟，未知 Native 不自动再唤醒上级，只有确定不可达才沿配置关系向上。不能从 profile 名字猜 manager，不能以无回复超时判定上级解决失败。

## 受权恢复操作

`inspect` 为只读；`reconcile` 查询原操作，不产生新 Native 输入；`resume_receiver`/`prepare_receiver`/`rebind_receiver` 需要相应 management authorization、预期 binding revision 和审计；`retry_delivery` 由 Core 判据决定是否安全，按钮不能绕过 unknown fence。用户明确选择仍不能把未知改写成“此前未发生”。

恢复请求返回自己的 operation handle，其生命周期不同于原 Message。诊断界面应显示原问题与恢复操作两个状态，不以“修复已发起”显示“消息已送达”。
