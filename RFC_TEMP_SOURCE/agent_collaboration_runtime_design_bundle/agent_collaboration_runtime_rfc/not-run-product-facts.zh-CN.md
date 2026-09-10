# `not_run` 产品事实与验证边界说明

**说明日期：2026-09-09（Asia/Shanghai）**  
**适用对象：** Agent Collaboration Runtime / Control Plane 研究包、Implementation Master Plan、后续 Local / Cross-Machine / Hosted / Scale 产品 Profile。  
**权威来源：**

- `D:\Chatgpt\Agent-collaboration\RFC_TEMP_SOURCE\2026-09-08-cross-harness-runtime-final\acceptance-scenarios.json`
- `D:\Chatgpt\Agent-collaboration\RFC_TEMP_SOURCE\2026-09-08-cross-harness-runtime-final\validation-report.md`
- `D:\Chatgpt\Agent-collaboration\RFC_TEMP_SOURCE\2026-09-08-cross-harness-runtime-final\validation-results.json`
- `D:\Chatgpt\Agent-collaboration\RFC_TEMP_SOURCE\Implement-Master-Plan.md`

## 1. 产品定义

`not_run` 是产品事实账本中的正式验证状态：对应能力、验收场景、输入条件、断言和所需证据已经定义，但在指定的环境、版本、方向、授权范围和 Policy Profile 下，真实执行尚未发生，或执行结果尚未形成可审计、可复现、可引用的证据。

可以将它写成一个产品合同：

```text
not_run
= 已定义的验收合同
+ 尚未完成真实执行或结果尚未完成证据归档
+ 当前不能作支持承诺
+ 后续存在明确的验证 Gate
```

`not_run` 是范围化状态，而不是整个产品的永久标签。它必须绑定到具体的：

- 能力或验收场景；
- Machine / Node；
- Harness / Driver / Provider；
- OS、数据库、协议和组件版本；
- 消息方向或调用方向；
- Credential Scope 与 Policy Profile；
- 有效时间窗口；
- 所需的日志、receipt、read-back、故障注入和恢复证据。

单个场景的 `not_run` 不能外推为所有机器、所有 Harness、所有版本、所有方向或整个产品均处于同一状态。

## 2. 截至 2026-09-09 的产品事实

当前研究交付的状态是：

```text
Accepted architecture baseline
+
implementation-not-started
```

这表示 Pre-P0 / P0 的架构合同已经冻结，但不表示 Runtime、Control Plane、Node、Driver、Durable Operation Provider 或跨机器能力已经在产品中运行。

当前可以引用的事实包括：

- 现有 `Agent-collaboration` 仓库仍以 setup-only Skill、`AGENTS.md`、`.agents/knowledge/` 和文件协议为主。
- 现有仓库单元测试报告为 67 tests passed；Skill 结构、项目 setup、JSON 结构、schema/fixture、外部 Agent 边界和 manifest 完整性检查已通过。
- 最终研究包包含 34 个验收场景，编号为 `E2E-01` 至 `E2E-34`，当前全部为 `status: not_run`。
- `validation-results.json` 明确记录：

  ```text
  real_harness_tests = not_run
  cross_machine_tests = not_run
  authorization_cryptography_and_effect_safety = not_proven_by_json_schema
  ```

- 真实双机、异构 Harness、Session 恢复、跨机器投递、Lease/Fencing、外部效果不确定性和生产形态的托管能力仍需要后续工程阶段的真实证据。

已有的结构检查、来源审查和合成 fixture 证明的是合同和材料的一致性。它们不能单独证明真实 Harness 已经能够 send、wake、spawn、attach、resume、terminate 或提供 delivery receipt，也不能证明用户退出 UI 后任务一定继续执行。

## 3. 对用户和产品体验的含义

### 3.1 用户可以看到什么

产品可以展示：

- 能力名称和适用的 Profile；
- 对应验收场景；
- 当前状态为 `not_run` 的事实；
- 已有的结构、文档或局部测试证据；
- 缺少的真实证据；
- 目标验证阶段和预计 Gate；
- 所需授权、数据边界、回滚方式和恢复入口。

推荐的用户文案是：

```text
已定义｜待验证（not_run）
当前 Profile 尚无运行证据
完成对应 Gate 后评估是否支持
```

`not_run` 不应被呈现为产品故障告警，也不应被呈现为默认可用能力。它表示产品正在如实标记证据边界。

### 3.2 用户暂时不能依赖什么

在对应能力仍为 `not_run` 时，产品不能向用户承诺：

- 跨机器 Agent 已经可以稳定互相寻址和通信；
- 任意 Harness Session 都可以被后台唤醒或恢复；
- UI 关闭、Session 消失、Node 重启或 Harness 崩溃后一定会继续推理；
- 任意机器、版本、方向或租户都具有相同能力；
- Human Bridge 已经能够自动升级回系统管理 Transport；
- 外部副作用已经具备 exactly-once 语义；
- Hosted、租户隔离、计费、SLA、数据驻留和联合灾备已经完成产品支持。

### 3.3 未验证能力的运行行为

涉及未验证跨机绑定、后台执行、自动唤醒、受保护副作用或恢复路径的命令，应保持在明确的 `pending`、`not_run`、`waiting` 或 `blocked` 状态，直到满足相应的授权、能力、版本和证据条件。

系统仍可以处理已经提交且授权有效的确定性 operation，例如持久等待、重试、outbox 投递、对账和恢复记录；系统不会因 Session 消失而补写新的 Agent reasoning、delegation、Agent turn 或 WorkItem。后续推理、复核、修复和验收由外部 Harness 中的 Agent 或用户通过显式命令触发。

外部效果出现响应丢失或状态不确定时，产品应先显示“待确认 / uncertain”，并执行 operation marker、read-back、幂等和 fencing 检查；在事实确认前不能显示为成功。

## 4. 状态词典

| 状态 | 产品事实 | 可以对外说明 | 不能对外说明 |
|---|---|---|---|
| `confirmed-local` | 本地源码、测试或当前文件直接确认 | 指定版本和范围存在该事实 | 所有环境均支持 |
| `source-reviewed` | 官方规范、文档或维护者源码已读取 | 资料描述了某种能力或模式 | 本产品已经接入或部署 |
| `architecture-allowed` | 当前架构合同允许该方向 | 该方向未被架构排除 | 产品已有运行机制 |
| `implemented` | 已有实现代码路径 | 代码已经存在 | 正确、稳定、可发布或跨环境可用 |
| `tested` / `passed` | 某次具体测试在指定范围通过 | 该测试断言在该范围成立 | 产品级支持或普遍适用 |
| `unverified` | 可能存在实现或部署，但证据不足 | 保留为待核验事实 | 已确认或已支持 |
| `not_run` | 验收合同已定义，真实执行尚未发生或结果未归档 | 后续可按 Gate 验证 | 通过、失败或支持 |
| `blocked` | 执行受到环境、授权、版本、策略或资源条件阻塞 | 阻塞原因和解除条件 | 已完成验证 |
| `unknown` | 当前范围没有足够事实 | 需要进一步调查 | 任何正向能力结论 |
| `unsupported` | 当前合同、策略或 Profile 不提供该能力 | 当前范围不提供 | 仅靠补充文档即可获得支持 |
| `supported` | 命名 Profile 已满足完整支持合同 | 对指定范围、方向和有效期成立 | 自动外推到其他 Profile |

`Capability Observation` 至少应携带 Machine、Node、Harness、Version、Direction、Credential Scope、时间、Evidence 和 Policy Profile。Harness、OS、版本、凭据、拓扑或权限发生变化时，旧观察必须重新验证。

## 5. `supported` 的正式判定

`supported` 不是 `implemented` 或一次 `passed` 的同义词。只有下列五层证据全部存在时，能力才可以在命名 Profile 下升级为 `supported`：

```text
说明
+
决策逻辑
+
真实机制
+
不变量验证
+
代表性端到端证据
```

每一项支持声明必须带上：

```text
能力名称
+ 命名 Profile
+ Machine / Node / OS
+ Core 版本
+ Durable Operation Provider 版本
+ Driver / Harness 版本
+ 数据库和协议版本
+ Policy 版本
+ Direction
+ 有效期
+ Evidence Bundle
+ Gate Record
```

因此，下列推导均不成立：

- `source-reviewed` → `supported`；
- `architecture-allowed` → `implemented`；
- schema/fixture PASS → Runtime PASS；
- 单机 PASS → 跨机 PASS；
- 一个 Harness PASS → 所有 Harness PASS；
- 一个方向 PASS → 双向能力 PASS；
- 旧版本观察 → 当前版本支持；
- 聚合测试全绿 → 代表性 E2E 已通过。

## 6. P0–P4 的验证升级路径

### P0：合同冻结与产品基线

P0 可以声称：架构、Scope/ScopeBinding、Domain authority、Inbox/Outbox、Lease/Fencing、数据边界、Provider/Driver 边界和验收合同已经冻结；结构校验、边界审查和 manifest 校验已经通过。

P0 不能声称：Runtime 已实现、真实 Harness 已支持、跨机能力已支持、用户退出后任务一定继续或外部效果具备 exactly-once。

### P1：Local Durable Vertical Slice

P1 的目标是在 `1302-1` 上形成一个命名的 Local Profile，验证 PostgreSQL、Node journal、Durable Operation Provider、MCP/CLI/HTTP 共用 Core、Driver、Receipt、Evidence 和 read-back。

P1 至少应执行：Core/Node/Provider/Harness 重启、Harness 崩溃、新 Attempt 或安全 resume、ACK 丢失去重、uncertain effect read-back、stale baseline、权限拒绝和 Acceptance 边界测试。

P1 通过后，产品最多声明：

```text
Local Alpha / named profile
```

并且必须绑定完整的版本、OS、数据库、Driver、Harness、Provider 和 Policy。第二真实 Driver 因环境、授权或条款无法验证时，状态应为 `blocked`，不能静默替换成支持结论。

### P2：Cross-Machine Runtime

P2 的目标是让不同机器、不同 Harness、不同 Session 的外部 Agent 经由 Runtime 完成真实闭环。必须验证 Node enrollment、认证通道、定向 Binding、mailbox/cursor/dedup、远程生命周期、Source/Artifact transfer、Lease/Fencing、网络分区、旧 Owner 复活、Human Bridge 和能力重新 Probe。

P2 通过后提交 `Cross-Machine Gate Review`，由产品所有者审阅 Project/Route/Agent/Machine 体验、自动化程度、Human Bridge UX、数据边界、用户退出后的可见状态、机器/Harness 可替换性和 Hosted 方向。

### P3：Hosted Product

P3 验证 Organization、Membership、OIDC、RBAC、租户隔离、Console、Usage/Budget、Backup/Restore、Retention、Export/Delete、数据驻留、密钥、Billing、SLA/SLO 和命名的 Hosted Profile。

P1/P2 的本地和跨机证据不能升级为 Hosted 支持。P3 未完成时，Hosted 能力继续保持 `not_run`、`unverified` 或 `blocked`。

### P4：Ecosystem / Scale

P4 验证 A2A Gateway、ACP/Driver SDK、Provider Conformance、更多 Harness、Schema Registry、版本协商、滚动升级、长任务迁移、排空、分片、扇出、背压、公平性和大规模可观测性。

P4 的每个新增 Harness、OS、版本、Provider 和拓扑都必须有独立证据，不能继承其他 Profile 的支持结论。

## 7. 34 个验收场景的产品分组

当前 `E2E-01` 至 `E2E-34` 全部为 `not_run`。详细 Given / Action / Assertion / Evidence 以 `acceptance-scenarios.json` 为准。产品展示可以按以下主题分组：

| 产品主题 | 场景范围 | 主要目标阶段 |
|---|---|---|
| 跨机协作、网络、消息、定向 Transport | E2E-01、04、08、14、15、16、17、18、19、20 | P1/P2 |
| UI、Session、Harness、Node 和 Provider 连续性 | E2E-02、03、05、06、07、21、26、27、29 | P1/P2/P4 |
| 外部效果、基线、Evidence 和 Acceptance | E2E-09、12、13、25、33 | P1/P2 |
| Lease、Fencing、人工接管和权限 | E2E-10、11、22、28、34 | P1/P2/P3 |
| 恶意输入、租户、数据和安全边界 | E2E-23、24、31、32 | P1/P2/P3 |
| 预算、背压、计量和商业运营 | E2E-30 | P3/P4 |
| 迁移、Hosted 和规模化连续性 | E2E-29、31、32 | P3/P4 |

分组用于产品视图和 Gate 管理，不改变场景自身的唯一 ID、验收合同或证据要求。

## 8. Gate 证据合同

每个 Gate 至少记录：

- 命名 Profile；
- Machine / Node / OS / Harness / Driver / Provider / 数据库 / 协议版本；
- 拓扑、Direction、Credential Scope 和 Policy 版本；
- 场景 ID；
- Command ID、Operation ID、Message ID、Event ID 和 Receipt；
- 测试开始和结束时间；
- 原始测试输出和失败注入记录；
- Source、Artifact、External Effect 的 read-back；
- 恢复轨迹、未决问题、阻塞原因和负责人；
- Gate 结论及其有效期。

`PASS` 只对该 Gate 的命名范围成立。缺少必需证据时，应使用最具体的 `not_run`、`not-measured`、`unknown` 或 `blocked`，而不是用聚合绿色测试替代真实端到端证据。

受保护副作用在授权、Lease generation、fencing、Effect Gateway、幂等和 read-back 尚未齐全时必须 fail-closed。无法 fencing 的共享资源在旧 Owner 未隔离或未确认终止前保持阻塞。

## 9. 对软件团队的执行要求

1. 将 `not_run` 作为一等产品状态写入支持矩阵、Gate Record、Evidence Bundle 和用户可见状态模型。
2. 不因 RFC、设计图、文档、schema、fixture 或模型叙述存在而自动启动外部 Agent、上传源码或改变既有权限。
3. 每个真实验证都固定环境、版本、方向、授权范围、Policy 和回滚方式。
4. 只恢复已经提交且授权有效的 operation；后续 Agent reasoning、delegation、review、repair 和 acceptance 由外部 Agent 通过显式命令提交。
5. UI、Session、Node、Harness 或 Provider 消失时，优先保留 durable domain state、Receipt、Evidence 和 Binding 历史；不把未提交的决策补写成系统事实。
6. 任何支持声明都必须能回指到具体场景、命令、事件、receipt、read-back 和 Gate Record。
7. 产品发布说明应同时展示“当前可用 Profile”和“仍为 `not_run` 的能力”，避免把研究包状态误读为产品支持状态。

## 10. 结论

`not_run` 是一种保守、可追踪且对产品负责的状态。它保留已经冻结的产品意图、验收合同和验证路线，同时明确当前没有足够的真实运行证据。

在具体命名 Profile 完成相应 P1、P2、P3 或 P4 Gate，并满足五层支持合同之前，产品应持续展示“已定义、待验证”的事实边界；涉及未验证能力的受保护操作保持显式授权、可审计、可恢复和必要时阻塞。

当证据达到要求后，状态可以从 `not_run` 升级为 `passed`、`verified`、`blocked`、`failed` 或 `supported` 等更具体的产品事实；升级必须针对明确范围，不能通过泛化或继承自动完成。
