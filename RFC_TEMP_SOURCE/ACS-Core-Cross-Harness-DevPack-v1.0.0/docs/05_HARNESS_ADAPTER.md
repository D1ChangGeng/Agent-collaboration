# 05｜Harness Adapter 通用能力契约

## 接口与适配范围

见 `contracts/adapter_protocol.py`。Adapter 必须提供 describe、observe、admit_input、reconcile；prepare_receiver/subscribe_observations/restore_receiver 为能力声明的可选接口。没有能力时返回 typed unsupported，而不是空对象或假 Session。

所有参数来自 Core 受权封存 command；Adapter 不能从自然正文推导 sender、授权、路径或运行身份。Adapter transport 和 Node enrolled identity 分别认证。

## 能力模型

每项 Capability 有 `support=supported|unsupported|unknown` 与 `availability=available|temporarily_unavailable|unknown`。支持不代表当前可用。证据绑定具体 provider kind/version、execution host、binary/config 指纹、账号作用域、adapter version、connection epoch，过期或变化后重新验证。

必须区分：原生结构化输入、输入查询、原生幂等键、安全 busy 排队、安全 mid-turn steer、可恢复 Session、允许新建 receiver、input consumed 事件、原生观察订阅、只读 transcript、approval round-trip、附件可达性、终端提示能力。所有默认未知，不能由 Harness 品牌推断。

## 观察模型

观测轴独立：transport connection、process presence、session presence、input readiness、native blocker。每项含 `knowledge=observed|inferred|unknown|unsupported`、source、observed_at、expires_at、binding epoch/generation 与 evidence ref。

事实优先使用当前原生接口；hook 需绑定受信进程代次；PTY heuristic 只能标推断。不能把屏幕安静当 idle，不能把窗口不在前台当离线。来源冲突应显示 conflict/unknown 并拒绝不安全输入，不按“更乐观”的状态继续。

## 输入策略

| 真实状态/能力 | 行为 |
|---|---|
| current + ready + 身份/权限仍有效 | 按持久 operation 提交 |
| busy + verified enqueue | 放入原生队列，receipt 表明 queued 而非 consumed |
| busy + 无安全排队 | Core deferred，等待状态变化/有界重查 |
| 等待人类 approval/question | 不输入同意/回车；通知正确决策入口；原审批只由 Harness/宿主权限处理 |
| 用户草稿/不清楚输入栏内容 | 不抢占/清除输入；待可安全接收 |
| 原生 rate limit/auth blocked | 可见阻塞，按原生恢复时间/授权动作继续，无无限重试 |
| 原生实例不存在但允许 resume | 受权恢复原 session；不能 read API 隐式恢复 |
| 仅能新建 Session | 需明确配置许可，绑定新 epoch，hydrate 最小通信上下文 |
| 结果未知/身份漂移 | reconcile；禁止尝试另一个未证实目标 |
| capability unsupported | Inbox 保留，Native 阶段 unsupported，提供正确 remediation |

mid-turn steer 不作为最低能力。只在原生明确支持、策略允许且没有人工输入冲突时可用；“统一接口”不要求所有 Harness 都模拟相同执行控制。

## 初始交付配置

A. **现有 Codex Adapter**：复用生产 Driver/receiver；升级 capability/observation/operation evidence；运行既有 OS 范围回归。B. **现有 OpenCode Adapter**：同等语义，不自动扩大 Shared/Windows 支持声明。C. **Orca-owned receiver Adapter**：通过宿主 session bridge 注册并接收，原生输入仅由 Orca Host 执行，Core 不同时用另一个 Driver 启动同一 Session。D. **generic terminal receiver**：能力框架与拒绝/降级必须实现；无真实安全准入证明时仅只读观察，不以模拟键入承诺安全送达。

新的 Claude/Pi/其他原生 Driver 不是本轮无条件全覆盖任务；Orca 支持某 Harness 不等于 ACS 独立 Driver 已资格化。通过 C 路径继承的是宿主已确认能力和受权 session，不是名称对应的全部功能。

## 配置和扩展

安装阶段确认运行主机/账号，敏感凭据保留现有私有机制。Adapter manifest 不能包含明文 Token。支持版本范围可声明，但 runtime probe/契约校验仍需执行；启动时不自动下载并执行不可信 CLI。未来新增 Driver 通过同一 conformance suite，不添加 Agent-facing 专属发信工具。

## 跨语言 bridge wire

`contracts/adapter-wire.schema.json` 定义 NativeAdmissionCommand/Result。Python Protocol 为进程内接口，TypeScript port 为集成边界，二者序列化必须通过该 wire schema。sealed_envelope 保留既有已登记 receiver 的签名封装原始字节（base64 只是运输编码），不引入新密码协议；format 只能是握手确认的既有封装版本。接收者必须独立验证原 envelope，不能信任外围未验证字段。

外围 operation/hash/epoch 与封存内容不一致必须拒绝。Describe/observe/reconcile 通过已受信连接并重新核验权限；NativeAdmissionResult 中 accepted/queued 仅表示原生接纳，definitively_not_admitted 必须有真实无副作用证据；unknown 不提供重试授权。
