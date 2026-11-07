# 11｜Orca 工程吸收映射

本章不是对比研究任务。Codex 在实现每个工作包时阅读对应源码，提取必要机制并复用 ACS 既有路径。来源状态与 commit 见 sources。

| Orca 参考模块 | 要吸收的机制 | ACS 落点 | 明确不移植 |
|---|---|---|---|
| mailbox-notification-coordinator | 活动 wait 与自动唤醒竞争协调；提交后通知 | communication_dispatch/现有 wait lease | Run 消费所有权作为普通通信前置 |
| mailbox-pointer-delivery / stage / submit / resume | 输入分阶段、回车未知窗口、busy/draft 保留 | 受控 terminal Adapter 与 operation evidence | 全局 PTY 管理器、任务终态 |
| structured-mailbox-pointer-delivery / structured-mail-custody | 原生消息队列、旧操作先核验、重复输入防护 | Native input ledger + Adapter reconcile | dispatch mailbox 的生存期绑定 |
| structured-agent-session-input-readiness | handoff 前再检查 current child/readiness/approval | receiver 最后一道准入检查 | Harness 内部调度/工具控制 |
| agent-state-rules / hooks projector | 多来源状态、推断强弱、实际版本能力 | Observation 契约、证据时效 | 静默等于 idle 的无证据推断 |
| federation relay enqueue/ack/import/sync | peer capability、序号/ACK、断线调和、有界队列 | 现有 Node/Receiver transport | 联邦 Task owner 和 Worker 生命周期 |
| native-chat-types / agent-session source | 来源、原生 row、工具/结果/子 Agent/后台任务结构 | NativeViewProvider + exact linkage | ACS 原生 transcript 主库 |
| plugin Host API / manifest / hooks | capability 审核、调用 surface、事件订阅 | 插件 worker/bridge adapter | 认为 UI action replacement 可替换整个通信引擎 |
| send-point-to-point / ask / preamble | 识别普通消息与任务控制耦合处 | 保留自然 send/reply_to；通信上下文注入 | worker_done、Gate、Task DAG 作为必需协议 |

## 吸收决策记录（每项）

记录 upstream revision/path/symbol、观察到的事实、现有 ACS 对应点、gap、选择（reuse principle/adapt code/no change）、权限/副作用/回滚影响、测试 IDs。仅因文件名相似不能判断已覆盖。main 中有代码、测试文件存在、测试实际执行通过、产品版本资格是四个不同等级。

## 代码复用原则

优先保留 Python runtime 与已有服务，不为搬运 TypeScript 强迫跨语言服务化。确实复用上游片段时记录 license/notice、修改范围和 provenance。上游参考代码不随本包复制；实际实现时以目标仓库许可和第三方声明核对，不能把所有代码自动重新许可。不得复制上游凭据、测试私信或用户路径。

## 查阅范围控制

每个 WP 只阅读相关入口、状态存储、调用者和对应测试，随后直接开发。发现接口缺口按既定边界实现 bridge 或 typed unsupported，不重新发起全面产品调研、UI 视觉探索或比较实验。
