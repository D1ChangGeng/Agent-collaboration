# Agent Collaboration Runtime / Control Plane — Architecture RFC v2

**状态：Accepted architecture baseline / implementation-not-started；本文件定义后续实现采用的 Canonical Delta。**  
**研究截止：2026-09-08（Asia/Shanghai）。**  
**架构修订：2026-09-09（Asia/Shanghai）；外部 Agent 职责与协作基础设施合同已确认。**  
**设计目标：跨 Harness、跨 Session、跨机器、可恢复且默认由系统管理端到端通信的工程协作。**

## 0. 结论与证据边界

建设一个 **Harness-agnostic Collaboration Infrastructure + Control Plane**：外部 Harness 运行 Agent；Collaboration Runtime 保存长期身份、知识边界、协作状态、消息和绑定，并执行确定性的基础设施合同。Skill 提供操作指南、接入和生命周期 Surface。

推荐组合：

- 我们拥有：Scope / Root / Route / WorkItem、AgentSlot、accepted state、ownership / handoff、evidence / finalization records、能力解析、授权验证和协作恢复语义。
- 复用基础设施：PostgreSQL、Temporal、SQLite、对象存储、OIDC、策略引擎、操作系统进程管理和 OpenTelemetry。
- 统一接入：MCP + CLI + versioned HTTP API；A2A 用于外部 Agent 服务互操作；ACP / 原生 SDK / CLI 用于 Runtime Driver。
- 运行分层：逻辑 Control Plane、机器侧 Node、可替换 Harness Runtime、独立 Source / Artifact / Effect Gateway。
- 默认通信：system-managed end-to-end；Human Bridge 仅为经过评估、限时且可自动退出的恢复状态。
- 默认一致性：每个协作权威域一个权威写入方；允许分布式执行，不默认允许分区时多主修改同一 Task、Lease 或 AcceptedState。

研究证据覆盖两份设计输入、现有仓库、既有 RFC bundle 和公开一手资料。真实双机故障注入、Control Plane、Node 与 Durable Operation Provider 部署均为 `not_run`。本文的 Harness 矩阵是文档 / 源码级候选能力；附件规范已有的五层支持判定继续适用。[D1 §§3, 32, 99]

当前 `Agent-collaboration` 仓库的事实基线是：setup-only Skill、repository/Workspace/Route 生命周期脚本、`AGENTS.md` 与 `.agents/` 文件协议；本版未把这些文件协议改造成常驻运行时。仓库没有已验证的 daemon、MCP Server、HTTP/RPC/A2A 服务、事件库、队列、调度器、租约管理器、机器编排、Artifact Store、Web Console 或 durable execution engine。现有本地验证只覆盖 setup/metadata 行为；跨 Harness、跨机器、断线恢复、权限隔离和外部效果安全仍属于未运行场景。

本文中的 MUST / SHOULD 表示本次确认的设计合同。设计采纳、第三方公开能力、部署实例验证和完整产品支持分别记录；第三方版本锁定与真实 conformance 在工程 Gate 中验证。

## 1. Canonical Baseline 的保留与修订

### 1.1 必须保留

Root 与 Route 的长期身份；Session 可替换；Endpoint 替换不改变 Route；Root 负责治理和发现，Route 负责自身高频状态；源码、消息、源码访问与证据独立；AGENTS.md 只放稳定上下文；`.agents/knowledge/` 保存有未来行动价值的知识；迁移默认非破坏；最终交付依据 accepted state 和真实 read-back。[D1 §§7–18, 19–25, 41, 57–62, 69–72]

### 1.2 必须显式修订

| 现有条款 | 新合同 | 迁移要求 |
|---|---|---|
| §36、§37、§89.9：direct 不成立则 user relay，user relay 为正常 transport | 优先建立、恢复或切换系统管理链路；Human Bridge 仅为最后恢复路径 | 更新推理指南、配置、机制、验证器和场景测试，不能只改描述 |
| §6：项目资产 + Harness Runtime 承载正常协作 | 外部 Harness Agent 承担推理和工程执行；独立基础设施进程保存并恢复已提交操作 | 保留既有目录 Scope 与知识；后台调用使用显式授权与可验证的外部 Harness 绑定 |
| §18、§90.17：能力观察本地化 | 本地为事实来源；可上报带范围、时间、版本与证据的 observation projection | 不能把机器 A 的能力升级为项目或 Harness 品牌的永久事实 |
| §48：transport change 为协作配置迁移 | 不改变权限、数据驻留、成本边界的 Provider 切换是运行时重新解析 | 改变信任域、源码位置、云端披露等仍须显式授权 / 迁移 |
| §61：仅在证据证明有必要时引入 workflow engine | Durable Operation Provider 处理已提交命令的 timer、retry、wait、outbox 与 reconciliation | Provider conformance 验证操作持久性；外部 Agent 的推理和委派策略由其 Harness 承担 |
| TaskQuay 分析中的 Host 持续主导 | Management Role 由外部 Harness Agent 承担；系统保存 Root Scope、AgentSlot、Session Binding 与协作事实 | Session 结束后保留身份与待处理状态；继续推理依赖可用或重新绑定的外部 Agent |
| Scope 与 Session 的关联 | Root、Route、Engineer Source Scope 分别维护身份、AGENTS、durable knowledge 与协作状态 | Source Workspace 可独立于管理目录；目录位置通过 ScopeBinding 显式记录 |

交接对象分别记录拒绝、过期、提交和完成；任务执行生命周期独立于 Handoff 对象。[D2 §8.2]

## 2. 外部 Agent 与协作基础设施边界

### 2.1 外部 Agent 与横向协作基础设施

产品组织为 `User → Root / Management Agent → Route Agent → Engineer Agent`。后三层均为外部 Harness 中的真实 Agent。Reviewer、Specialist、Finalizer 是外部 Agent 可承担的职责；角色、团队规模、委派对象、任务拆分、沟通关系、Review 策略和下一步行动由外部 Agent 决定。

Collaboration System 横向支撑各层 Agent。它接收外部 User、AgentSlot 或 Operator 提交的命令，校验权限、revision、资源与证据，持久化协作事实，解析已指定目标的地址，可靠投递，并恢复已授权的操作与 Session Binding。系统拥有身份、连续性、连通性和协作状态；Harness 拥有模型上下文、reasoning、planning、tool calling 和 Agent 自身的 orchestration。

系统内部的状态机只实现确定性的投递、重试、资源准入、租约、fencing、reconciliation 和生命周期恢复。`AgentRole` 是声明性职责元数据；组织层级与按需有向通信图独立，消息可以跨 Route 或跨职责层级发送。Agent Graph、Agent Planner、Team Builder、Supervisor Agent 和 LLM Workflow 属于外部 Harness 的实现边界。

### 2.2 基础设施层次

**网络可达不等于 Agent 可执行。** 系统端到端协作需要可验证的发送、目标收件、消费 / 调用、响应与恢复路径。只有 MCP 工具调用权限的交互式客户端，不能因此被当作可后台唤醒的模型进程。

**接入 Surface 不等于 Message Transport。** MCP、CLI、HTTP 是调用 Surface；HTTP / WebSocket / IPC 是网络或进程传输；原生 Harness API / ACP 是运行时控制边界；Temporal 是执行持久性设施。它们不能放在同一层做简单优先级排序。

**恢复有四种不同含义。** transport cursor 恢复、Task checkpoint 恢复、Harness 原生会话恢复、进程 / 文件系统恢复应分别表达。任一成立不能证明其余成立。

**E2E collaboration 不等于密码学 E2EE。** 有中继的自动协作仍是端到端功能链路；中继看不到明文则是另一个安全 Profile。

**“无限拓扑”不是无限资源。** 模型不设固定 Agent / Route 数上限，但必须有并发、扇出、任务数量、预算、速率和存储限制。

**能力等级不是严格线性阶梯。** 能 spawn 的 Harness 不一定能 attach 任意既有 UI 会话；能 resume transcript 不一定能恢复文件。Level 0–4 可用作产品 Profile，底层依然使用正交能力向量。

## 3. 总体架构与组件边界

```text
External Agent organization
User → External Management Agent → External Route Agent → External Engineer Agent
                      Every Agent runs in its own Harness / Scope binding

Horizontal collaboration infrastructure, used by every Agent
Human UI / External Agent Session
                   |
           MCP / CLI / HTTP API
                   |
       Collaboration Application Core
       + Identity / Policy Enforcement
                   |
  +----------------+-------------------+
  |                |                   |
Domain Store   Durable Operation Provider  Transport Resolver
PostgreSQL     Temporal provider processes Inbox / Outbox / Receipts
  |                |                   |
  +----------------+-------------------+
                   |
       Authenticated Node Channel
    outbound HTTPS / WS / bounded poll
                   |
          Machine Collaboration Node
  +----------------+-------------------+
  |                |                   |
Local Journal  Node Process Controller  Effect / Source / Artifact
SQLite         ACP / SDK / CLI      Gateways and Providers
  |                |
  |       Replaceable Harness Runtime
  |                |
  +---------- AgentSlot binding
```

直接 native / peer 消息路径可以绕过中心数据中继，但必须维持同一消息身份、授权约束、收件确认和可恢复账本。不能绕过领域状态提交及受保护副作用的授权门禁。

| 组件 | 拥有的责任 | 不拥有的责任 |
|---|---|---|
| Collaboration Core | 外部主体命令、Scope/身份、版本检查、不变量、状态转移、领域事件 | Agent 推理、任务拆分、团队组织、原始聊天主存储 |
| Control Plane | 外部提交的任务与关系、授权、资源准入、验收记录、审计、查询视图 | 产品决策、开发优先级推理、Review 策略 |
| Durable Operation Provider | 已提交操作的持久等待、timer、retry、outbox、reconciliation 与恢复 | Agent 推理、计划、角色创建和业务验收判断 |
| External Agent Session Binding | Scope / AgentSlot 与外部 Harness Runtime / Session / Node 的绑定、调用与回执投影 | 模型上下文与 Harness 内部 Agent 执行循环 |
| Machine Node | enrollment、心跳、能力 probe、Runtime 生命周期、本地 journal | 与云端同时成为同一对象的独立写入主节点 |
| Runtime Driver | 将规范动作映射到 ACP / 原生 API / CLI，报告事实及错误 | 任务拆分、协作策略、验收和长期项目知识 |
| MCP / CLI / HTTP | 相同领域服务的工具 / 命令 / API 映射 | 三套独立业务状态机 |
| A2A Gateway | 外部 Agent 发现、委派、状态和产物映射 | 假定外部 Agent 具备本系统的 lease / source / acceptance 语义 |
| Source Provider | immutable baseline、工作区、Git / SSH 访问及同步 | Agent 地址发现 |
| Artifact Provider | blob、manifest、hash、权限和传输 | 判断测试结论为真 |
| Effect Gateway | 带版本与 fencing 的 push / PR / deploy / 外部修改 | 根据自由文本扩大授权 |
| Human Console | 展示 durable project truth、决策入口、人工接管 | 要求用户维护会话地址或搬运日常消息 |

逻辑分层不要求第一版拆成大量微服务。先采用模块化 Control Plane；Node 是独立部署和安全边界。MCP Server 的连接生命周期与后台 Core、Durable Operation Provider、Node 进程分离。外部 Agent 的存活、唤醒和重绑定能力单独验证。

## 4. 标准协议调研与采用方式

### 4.1 MCP：Agent 工具 Surface，不是协作身份系统

当前已发布规范为 **2026-07-28**：无状态、自包含请求和逐请求能力；Tasks 已移至可选扩展。[S01][S02][S03]

Tasks 扩展提供 `tasks/get`、`tasks/update`、`tasks/cancel` 和持久句柄；通知依赖客户端显式支持。没有 Tasks 支持时，普通 structured tool result 仍可返回我们自己的 `operation_id / task_id`，随后调用查询工具。**不要求每个 Harness 先升级 Tasks，协作才能运行。**[S03]

本 RFC 采用双代兼容 Surface：旧 MCP 协议与 2026 协议分别协商 / 映射；业务对象和领域状态不跟随 transport session 消失。协议 task 的 TTL 不等于 WorkItem 的保留期。MCP Tasks 完成只说明映射操作完成，不能自动证明工程目标已通过验收。

### 4.2 A2A：外部 Agent 服务互操作

2026-09-08 重新读取的官方 `latest` 页面包含 **v1.0.0** 标识。A2A 提供 AgentCard、Task、Artifact、streaming、push 和 SubscribeToTask；Send Message 的幂等在标准中是 MAY，不应误认为自带本产品要求的强制去重。[S04][S05]

推荐将我们的外部委派 Attempt 映射到 A2A Task；本系统 WorkItem、accepted revision、SourceBaseline、Lease 和 AcceptanceDecision 仍由自身模型持有。需要接入 coding collaboration 扩展时明确声明所需语义；对不支持扩展的服务降低信任和能力声明，而不是伪造支持。

A2A AgentCard 是能力声明 / 发现输入，不是当前部署实际可用的证明。公开协议的多租户路由字段也不能代替租户授权。

### 4.3 ACP：值得新增的标准化 Driver 边界

这里 ACP 指 **Agent Client Protocol**。其 session/new、session/prompt、session/cancel，以及按能力支持的 list / load / resume，适合减少每个 Coding Harness 的重复边缘集成。[S06][S07]

优先次序：可验证 ACP 接口 → 能覆盖需求的官方原生 API / SDK → 结构化 headless CLI → 有限 PTY 兼容。不是为了统一而强迫成熟原生 API 退化到功能不足的通用协议。

### 4.4 方案比较

| 方案 | 判定 |
|---|---|
| MCP-only | 适合工具接入；不足以独自承担机器 enrollment、进程监督、UI 退出后的模型调用与项目权威状态 |
| CLI-only | 可作完整自动化客户端；但把 shell 文本解析当统一 Agent 协议会扩大兼容与安全面 |
| Shared Core + MCP + CLI | 必须采用的基础模型 |
| Core + MCP + CLI + HTTP + A2A / ACP | 推荐目标；A2A 和 ACP 放在各自明确的边界，不另建业务内核 |

## 5. 同类系统的架构规律与已验证边界

| 系统 | 关键身份 / 持久层 | 已有能力与边界 | 对本系统的影响 |
|---|---|---|---|
| TaskQuay | 自身 agent / workItem 标识与 provider session 分离；SQLite、本地工作账本 | 主控直读、上下文引用、幂等键、session affinity、协作式资源协调；当前源码 restart reconciliation 会把活动 turn 标成可重试 error | 可集成本地执行网关或复用模块；不是已经验证的跨机器持久编排内核 |
| Temporal | Workflow ID / Run ID、Event History；独立 provider worker process | durable timers / retry / event replay；Activity 可能重复执行 | 集成已提交操作的持久性；领域 Task ID 与引擎 run 分离 |
| OpenHands SDK / Agent Server | Conversation、Workspace、事件和持久状态 | local / remote API 与应用分离；可作为完整 Agent runtime | 集成 Runtime Provider；不让所有 Harness 必须改写为 OpenHands Agent |
| Coder | Workspace、build / provisioner、workspace agent、control plane | 工作区 provisioning、连接与管理边界完整 | 企业环境可直接复用 Machine / Workspace 子域，不必重做 Terraform fleet |
| Claude Managed Agents | session log、harness、sandbox 分离 | 以独立接口替换早期耦合容器，分别恢复执行与会话；产品有自身保留策略 | 可作为托管 Provider；采纳解耦规律，不复制厂商 session 为 Root |
| Codex App Server | thread / turn / item + App Server | 结构化客户端控制和事件；不是通用跨厂商项目账本 | 原生 Driver 候选 |

依据：[S08]–[S19]。TaskQuay 的 cooperative claims 与 restart 标记限定在本地执行子域，不能作为跨机器持久编排证据。[S08][S09][S10]

Anthropic 工程文章支持将 session、harness、sandbox 分别持久化和替换；该来源仅支持这一解耦方向，不作为其他项目基础设施状态的判断依据。[S17]

## 6. Build / Buy / Integrate / Extend Matrix

| Capability | Candidate | Reuse Mode | What We Own | Main Risk | Recommendation |
|---|---|---|---|---|---|
| Collaboration domain | 自有 Core | Build | Root / Route / WorkItem / accepted state / handoff / evidence | 领域边界膨胀 | 核心投资 |
| Durable operations | Temporal；备选 DBOS / Restate | Integrate | 已提交操作、确定性恢复合同、版本化重试政策 | 引擎历史与 DB 双写、版本演进、运维 | 以 Temporal 为首个参考实现 |
| External Agent reasoning / orchestration | 外部 Harness Agent | Harness-owned | 命令、绑定、回执和协作状态合同 | 混淆 Agent 决策与基础设施执行 | 由外部 Harness 承担 |
| Authoritative state | PostgreSQL | Integrate | Schema、事务、不变量、domain events / outbox | 热点、迁移、灾备 | 直接使用，不自建数据库或共识 |
| Node journal | SQLite | Integrate | operation journal、inbox / outbox、恢复指针 | 单盘损坏、磁盘满、未 fsync 的 ACK | 本地事务持久化，不承担分布式主库 |
| Messaging | PostgreSQL outbox；NATS JetStream | Compose | packet、mailbox、业务去重和 receipt | broker ACK 被当执行完成；保留窗口 | 初期可 outbox dispatch；扩展吞吐用 JetStream |
| Runtime control | ACP、Codex App Server、Claude SDK、CLI、OpenHands Agent Server | Integrate / Wrap | capability contract、统一错误与恢复语义 | 原生功能 / 版本不一致 | 薄 Driver + conformance suite |
| Machine / workspace | 已有设备 Node；企业 Coder | Integrate / Extend | Endpoint binding、授权、调度条件 | 引入整个平台的运维及许可证边界 | BYO workstation 默认；Coder 为企业 Provider |
| Connectivity | outbound HTTPS / WS；Tailscale；既有 SSH | Compose | application mailbox、节点信任与绑定 | 网络联通被当 Agent addressability | 不自建 NAT traversal / VPN |
| Process persistence | native OS process supervisor、systemd / launchd / Windows service；容器；tmux | Integrate | 生命周期合同、进程绑定、checkpoint mapping | PTY 解析；终端存活不等于重启恢复 | 官方 headless 优先，tmux 有限兼容 |
| Artifact storage | S3 / 经验证兼容对象存储；本地 immutable blobs | Integrate / Wrap | manifest、ACL、evidence link、retention | 数据驻留、损坏、GC、缓存投毒 | 对象存储 + 内容摘要；不自建分布式 blob 系统 |
| Build caching | Bazel Remote Execution / CAS 兼容系统 | Integrate | 输入基线与验证策略 | 非可复现结果误复用 | 仅用于适合的 build / test，不缓存任意副作用 |
| Authentication | OIDC IdP / Keycloak | Buy / Integrate | 账户映射、enrollment policy | issuer / audience 错误、token 混用 | 不自建 OAuth 授权服务器 |
| Authorization | OPA；关系授权复杂时 OpenFGA | Integrate | 领域角色、作用域、委派与审批规则 | 策略过期；过早堆两套系统 | OPA 或适配已有策略；OpenFGA 按需 |
| Secrets / workload identity | OS keychain、KMS / OpenBao、SPIFFE / SPIRE | Integrate | credential refs、最小授权、节点绑定 | sandbox 取到控制面密钥 | 密钥不进 prompt / packet / 全局日志 |
| Observability | OpenTelemetry + 现有 collector / backend | Integrate | 领域 correlation、卡住状态、证据质量指标 | 敏感上下文泄漏、高基数和账单失真 | 默认不采集 prompt / 源码正文 |
| Usage / billing | 自有 usage ledger + Stripe Billing 等 | Buy / Integrate | 计量事件、预算预留、provider reconciliation | 重复计费、迟到记录、供应商限制 | 账本与支付分离，不自建支付基础设施 |
| Notifications | 既有邮件 / webhook / push provider | Integrate | 通知政策、审批对象、去重 | 通知丢失或被当权威状态 | 通知只提示重新读取 durable state |

基础设施依据：[S11]–[S15]、[S19]–[S32]。

### 6.1 Durable engine 专项决策

| 候选 | 匹配边界 | 主要优势 | 主要代价 / 限制 | 推荐位置 |
|---|---|---|---|---|
| Temporal | 已提交操作的 timers、retry、history、跨机器 provider worker process | durable execution 与 Client/Server/Worker 基础设施分层 | 引擎运维、确定性、版本迁移；Activity 仍可能重复 | Level 3/4 首个参考实现 |
| DBOS | PostgreSQL-first 的应用内 durable workflow、queue、schedule | local-first、部署面较小、MIT | 数据库/SDK 耦合；fleet、machine trust、lease/fencing 仍由本系统承担 | 低占用 Local Profile 候选，须通过同一恢复合同 |
| Dapr Workflow | 已采用 Dapr/Kubernetes/sidecar 的平台 | workflow、timer、external event 与跨应用集成 | activity 至少一次；依赖 sidecar、state store 与平台运维 | 既有 Dapr 环境的 Provider，不作为默认安装 |
| Restate | durable invocation、journal、keyed state | 单二进制与强 durable handler 模型 | BSL 1.1；托管多租户控制平面使用边界需法律/商业许可评审 | 实验性或内部 Provider；不作为默认 hosted core |

Temporal 作为首个参考 Durable Operation Provider 已接受，验证条件是已提交操作的恢复正确性与目标部署占用。P1 环境 Gate 测量占用、恢复时间、升级和运维成本；不满足命名 Local Profile 时，以同一 Domain/Command/Attempt/Effect 合同验证 DBOS。首个发布 Profile 只实现一个恢复 Provider。[S11][S12][S13][S14]

许可证已检查的样本：Temporal、DBOS Python、OpenHands SDK 为 MIT；NATS Server 为 Apache-2.0；Coder 主 LICENSE 为 AGPL-3.0（特定商业模块须另查）；Restate 当前为 BSL 1.1，附加授权区分内部 / 自有抽象应用与对第三方暴露 Restate 平台 API 的服务。不能笼统称其为“禁止 SaaS”，也不能称 BSL 为 OSI 开源许可。所有集成都应锁定发布物、SBOM 与许可快照。[S33]–[S38]

## 7. Canonical Domain Model 与 Ownership

保留原有名称和身份。`Scope` 保存长期身份与知识边界；`AgentSlot` 表示在该 Scope 中承担职责的可寻址逻辑协作者；`ScopeBinding` 记录二者与目录、角色及授权的版本化绑定。外部 Runtime、Session、Harness、Machine 均可替换。

| 对象 | 语义与权威 ownership |
|---|---|
| Organization / User / ServicePrincipal | 账户域；人的身份与机器 / Agent 服务身份分离 |
| Project | 产品视图、成员、配额；引用现有 Collaboration Root，不替换 Root ID |
| CollaborationRoot | 一个 collaboration world 的长期治理 / 发现实体；高频任务状态不写入 Root AGENTS |
| Route | 长期目标、决策、知识和 open loops；不是 transport routing entry |
| Scope | root / route / engineer_source；长期身份、职责、目标、AGENTS、knowledge、policy 与 collaboration state 引用 |
| ScopeBinding | scope_id、agent_slot_id、role、authority、directory/source binding、有效期与状态；重绑定保留历史 provenance |
| AgentRole / AgentSlot | Role 为外部声明的职责元数据，Slot 为 Scope 内可寻址协作者；Slot 绑定多个历史外部 Runtime |
| WorkItem / Task | 可验收工作单位、依赖、scope、deadline、budget；独立于连接存在 |
| ExecutionAttempt | 一次实际执行尝试；Task 重试创建新 Attempt，不改旧执行事实 |
| AgentRuntime / HarnessSession | 外部 Harness 中真实 Agent 执行实例的生命周期投影与会话引用 |
| Machine / Node / Endpoint | 设备身份、机器侧执行服务、逻辑执行目标分别建模；一次启动使用 boot / incarnation 标识 |
| CommunicationBinding | 有向协作者关系、desired policy 和当前 provider 解析结果；一条 Route 可有多个 binding |
| Message / DeliveryAttempt / Receipt | 逻辑消息、传输尝试和分层确认独立 |
| Resource / Claim / Lease | 资源、申请、带 generation / fencing 的授予；持有者绑定 Attempt / Runtime |
| Handoff | 上下文交接或 ownership transfer 的协议对象；不是整段工程执行状态机 |
| SourceBaseline | 仓库身份、commit / tree、dirty / untracked 内容清单、子模块 / LFS、环境引用 |
| Artifact / Evidence / ExecutionReceipt | bytes 引用、证据主张和实际执行回执分别建模 |
| AcceptedStateRevision | 不可变接受状态；包含 parent、基线、证据、决策者、policy version |
| AcceptanceDecision / SurfaceManifest | 接受理由和每个最终用户表面的生成 / freeze / read-back |
| PolicyGrant / ApprovalRequest | 被授权能力及需人决策的问题；不能由 packet 自我授予 |
| Event / UsageEvent / AuditEvent | 领域事实、用量与审计分别保留；不是聊天转录 |

对象可先在较少数据库表中实现，不要求一个名词一个服务。

Root Scope 位于管理工作区，保存产品目标、Route 状态、跨 Route 约束和里程碑；Route Scope 位于独立 Route 目录，保存该开发线目标、架构决策、Source State、Evidence 和 open loops；Engineer Source Scope 绑定真实 Source Workspace / Repository，保存工程规则、基线和证据。Source Workspace 可以位于管理工作区之外或另一台机器。Root Agent 默认通过 Route 汇报、Evidence 和 AcceptedState 管理产品；Route Agent 按 Grant 读取相关源码；Engineer Agent 按资源 Lease 操作源码。

Scope identity 独立于绝对目录路径；目录、机器与 Source binding 可迁移。每层 `AGENTS.md` 与 durable knowledge 保持自己的边界，权限允许时以引用共享。接替的外部 Harness Session 通过 `scope.attach / agent.bind` 恢复相同 Scope / AgentSlot，读取现行 AGENTS、知识和协作状态，然后由该外部 Agent 继续原职责。

## 8. 权威状态、事务与离线边界

### 8.1 Single authority

每个权威域记录 `authority_id + authority_incarnation + home_location`。同一 Task / Lease / AcceptedState 只允许一个权威写入路径。HA Control Plane 是同一个逻辑 authority 的多个实例，不是多个独立主库。

| 数据 | 首选权威 |
|---|---|
| Root / Route 长期身份与项目规则 | 原有项目 manifest / 项目文档；导入和采用版本显式记录 |
| accepted revisions、Task、Lease、Approval | 该 authority 的领域数据库 |
| 源码实际内容 | repository / immutable source snapshot |
| Artifact bytes | 对象存储或本地 blob store；manifest 校验完整性 |
| runtime capability、PID、session path、进程状态 | 本机观察；Control Plane 仅保存有有效期的投影 |
| transcript / provider context | Harness 存储；有需要时导出，但不成为项目知识 |
| operation history / timers | Durable Operation Provider；已提交操作的执行记录 |

不要让 markdown、PostgreSQL 与 Temporal 各自接受冲突写入。markdown task 文件在 runtime adoption 后可以成为导出视图或经校验的命令输入，不再与数据库双向任意写入。

### 8.2 事务边界

领域命令在同一个 PostgreSQL 事务中完成：

`validate grant + expected_revision + state transition + event append + outbox append + command dedup record`

事务提交后才报告 `accepted_by_authority`。Outbox dispatcher 可以重复发送；消费者按 command / message identity 去重。Temporal 接受 outbox 信号，执行已提交操作的 timer / retry / reconciliation，以受限服务身份回报操作事实；后续新 Goal、WorkItem、AgentSlot、委派与接受决定仍需要外部主体命令。

数据库事务和 provider RPC 不构成原子提交。必须有 outbox 重试、事件版本去重与定期 reconciliation。Provider 暂时不可用时，已提交任务仍可查询；恢复后继续已授权操作。

领域事件日志不要求所有对象从第一天起采用 full event sourcing。推荐“事务状态 + append-only domain events + 可重建读模型”，保持 schema 演化、数据删除和恢复可管理。

### 8.3 离线

云端 authority 暂时不可达时，Node 可以在**仍有效的授权**内完成隔离工作区中的已授予操作并缓存 evidence。不得离线续租全局排他资源，不得自行接受结果，不得凭旧 grant 发布到受保护分支或生产系统。

在仍有效且可本地验证的既有授权下，Control Plane 暂不可达不必阻止 Node-to-Node 消息和隔离工作；Node 保存消息与回执 journal，重连后同步。此时本地收件确认不能伪装成新的全局领域状态提交，缓存地址、grant、generation 仍须校验。

纯本地部署的 authority 本来就在本地，可以继续执行本地域内已提交且获授权的操作。外部 Agent 可跨权威域提交委派命令；最终接受与共享资源权威仍须明确。

从 local 迁移 cloud 必须先 drain / checkpoint、完成旧 authority 写入围栏，再 import 和切换 epoch；不允许失联时双方自行宣布为主。灾备恢复旧数据库时必须处理 incarnation 更新和旧 grant 失效，防止 fencing counter 倒退后旧执行者复活。

## 9. Collaboration Packet 与统一 API

传输不携带整个聊天历史。Packet 继续保留 Positive Goal、Accepted State、Current Request、Constraints、Source Baseline、Required Context、Artifacts、Expected Evidence、Response Contract。[D1 §§34–35, 70]

新增机器可校验 envelope：schema / message / correlation / causation IDs、project / route / task refs、sender / recipient AgentSlot、deadline、accepted revision、scope / grant reference、context / artifact digest references、回复合同。**grant_ref 只是引用，不能由调用者任意填写即获得权限。**

创建或改变 Goal、WorkItem、AgentSlot、委派、Handoff、Review 与 Acceptance 的请求必须追溯到认证的外部 `user | external_agent_slot | operator` 主体。`requested_by` 记录外部 AgentSlot、Runtime 和 Harness Session 引用；服务进程的 retry、receipt、lease 和 reconciliation 事件携带原 command_id / authorization lineage，权限只覆盖该已提交操作。Packet 中的 `context_policy`、`response_contract` 与 task 正文是给外部 Agent/Harness 的输入合同，由外部 Agent 解读和执行。

逻辑消息内容与 `DeliveryAttempt.provider / connection / retry_count` 分离。切换 native、relay 或 Human Bridge 不更换 message_id；任务内容或 scope 真正改变时创建新消息 / revision，并标记 supersedes。

| API 家族 | 代表动作 |
|---|---|
| Identity / discovery | project.discover、route.attach、agent.resolve、capability.probe |
| Task | task.create、get、revise、schedule、cancel、checkpoint |
| Messaging | message.send、inbox.receive、message.ack、request.respond |
| Waiting | event.wait、subscribe、resubscribe、snapshot |
| Runtime | runtime.spawn、attach、invoke、interrupt、resume、terminate、inspect |
| Coordination | claim.acquire、renew、release、handoff.offer、prepare、commit |
| Source / artifacts | baseline.capture、assert、artifact.upload、download、seal |
| Evidence / acceptance | evidence.submit、receipt.inspect、acceptance.evaluate、acceptance.commit |
| Human control | approval.respond、manual_control.acquire / release、policy.inspect |
| Finalization | surface.prepare、freeze、publish、readback、validate |

所有修改命令使用同一 CommandEnvelope：认证主体、idempotency_key、expected_revision、deadline、grant_ref、payload。相同幂等键不同 payload 必须冲突；不能静默复用旧结果。幂等记录保留期须覆盖可能重试 / 重放期；到期后旧命令应拒绝或经新操作合同重新提交。

HTTP / MCP / CLI 共用生成的 schema / service handlers；不承诺无限兼容旧 schema。未知安全关键字段或 required extension 必须拒绝，不能静默丢弃。

## 10. 动态 Transport Resolver 与 Human Bridge

### 10.1 以有向 Binding 为单位

```text
CommunicationBinding
  desired = system_managed_e2e
  current = native | node_relay | backend_relay | peer | human_bridge | unavailable
  requirements = durable_delivery / observable_receipt / data_policy / wake
  selected_provider
  selection_revision
  observed_capability_refs
  fallback_incident_ref
  recheck_after
```

Resolver 的实际输出应是可验证的 DeliveryPlan：AddressingProvider、MessageProvider、ActivationProvider、ReceiptProvider 及其授权 / 数据政策约束，而不仅是一个 provider 名称。源码与 Artifact 路径独立解析；能转发消息不自动意味着能唤醒目标或取得它需要的输入。

`temporary_disconnect` 是健康状态，不应作为 Provider 名称。双向通信可采用两个不同路径。广播应固定目标 membership revision，并记录每个目标的收件状态，而不是创建不受约束的全连接 mesh。

### 10.2 解析过程

1. 解析外部 Agent 命令已指定的目标协作者及两向执行条件。
2. 枚举已配置 / 可安全发现且获授权的 Provider 组合；不进行无边界网络探索。
3. 验证身份、地址、权限、投递、收件 / 消费以及响应路径。
4. 在满足安全、数据驻留、可靠性前提下优先复用 native；native 不满足时使用 Node / backend / peer path。
5. 对临时故障执行 retry、reconnect、resubscribe、切 endpoint、恢复 runtime；有预算、退避和负载上限。
6. 只有恢复预算已合理耗尽、无授权自动路径、任务必须继续且用户能桥接时，才创建 HumanBridgeIncident。
7. 新能力、机器重连、Harness 升级或用户报告新事实触发重新 probe；确认后立即停止发出新的人工转发请求。

“任何可行路径”的可检验含义是：**当前已接入或可由系统在授权范围内建立、协议与策略兼容、能够完成投递和执行闭环的路径**。不能承诺探索未知的所有网络连接，更不能突破授权去“修复”政策拒绝。

### 10.3 Receipt 的真实含义

`accepted_by_authority → target_inbox_committed → runtime_dispatched → runtime_acknowledged → response_received`

这些是不同观测，不一定由所有 Provider 全部提供。HTTP 200、MCP 成功返回、broker ACK、PTY 文本出现，都不能自动提升为 Agent 已执行或任务完成。缺失的层保持 unknown。

### 10.4 切换不丢语义

新链路完成双向 challenge / ACK 及最小 request / response 验证后，原子更新 Binding selection revision。未确认消息以同一 message_id 重发；旧链路晚到的消息和人工包在接收 inbox 去重、校验 deadline / accepted revision，不能再次触发副作用。

不同链路可能乱序。以 task revision、causation 和接收端 precondition 校验约束状态修改；不承诺所有 Agent 消息的全局总顺序。

### 10.5 HumanBridgeIncident

记录 blocked_reason、attempted_paths、policy_version、证据、恢复预算结果、created_at、recheck_after、expires_at 和出口条件。未知能力与永久不存在必须区分。

人工包必须自包含、最小充分、带目标、消息身份、源基线、约束、必要上下文和回复合同。接收者无法解析的“内部私有路径引用”不算充分上下文。保持可验证字节 / 签名封装或明确内容完整性检查。用户只运输，不负责总结和协议判断。Human Bridge 不绕过身份、授权、撤销或数据外传政策。

用户声称“现在可以直连”是新证据输入，触发验证，不是无条件 confirmed，也不是被旧 fallback 配置忽略。

## 11. Runtime、等待与用户退出

### 11.1 Detached execution 的必要条件

外部 Management / Route Agent 提交 Goal / WorkItem、目标 AgentSlot 与 execution policy：允许的仓库 / 机器 / 行为、预算、截止时间、风险审批、context 策略及 Harness credential reference。Core 持久化这些明确命令；Durable Operation Provider、Node 和 Driver 继续投递与恢复已授权操作。下一步推理、任务拆分、通信对象和工程策略由外部 Agent 在自己的 Harness 中决定。

已授权的 Harness invocation 和外部 I/O 可以由可记录结果的 Activity / Step 承载；模型调用及上下文归外部 Harness。基础设施状态机只处理已提交命令的输入输出。外部调用返回后、结果记录前发生崩溃仍可能造成重复调用或计费，需 read-back 与幂等合同处理。[S11][S12]

UI 断开而外部 Agent Session 仍运行或可验证唤醒时，该外部 Agent 可以继续处理已收到工作。若外部 Session 消失且没有可用绑定，系统保存 WorkItem、Message、Evidence 和 pending operation，进入 `waiting / pending / blocked`，等待外部重新绑定或执行既有授权覆盖的恢复绑定；后续智能决策由恢复后的外部 Agent 作出。

### 11.2 Runtime 绑定与进程恢复

`external binding command → resolve endpoint → verify capabilities / grant → acquire claims → baseline preflight → spawn or attach → record binding → invoke`

spawn 自身也需要 operation_id 和本地 journal。数据库与 OS spawn 不可能简单原子提交；Node 重启先根据 operation label、process tree、boot_id 和 provider read-back 查找已启动执行，不凭原 PID 或重复命令盲目再启动。

原生 resume 可用且授权覆盖时复用相容外部 Session；否则按已提交恢复策略准备 Scope、accepted state、immutable baseline、checkpoint 和 evidence 引用，交给获授权的新外部 Session。恢复策略缺失或超出原 Grant 时等待外部命令。更换 Session 不更换 Scope、AgentSlot、Task 或 Route。

tmux 只提供特定范围的终端 / 进程存活能力，不能作为消息协议、身份或跨重启执行证明。未经控制的终端注入不作为 full autonomy 的可靠承诺。

### 11.3 Wait 的合同

`wait(predicate, cursor, max_wait)` 仅等待有界时长；超时返回当前状态和 cursor，不取消任务。长期依赖写为 durable wait condition / timer。订阅断开不改变 Task 生命周期。

订阅注册采用一致快照 / cursor 与增量 replay，避免“先查询，再订阅”漏掉事件。cursor 过期返回明确错误并重新获取 snapshot。通知是加速提示；持久状态查询和 reconciliation 是恢复依据。SSE / WebSocket 不承担唯一持久性。

### 11.4 人工接管

正常人工接管申请 ManualControlLease，停止自动投递新 turn，观察 / 中断当前动作，交接工作区。归还时重新读取源码并重建 baseline；不得把人工期间的旧测试视为仍有效。

用户在未纳管编辑器中直接修改共享目录仍可绕过 cooperative lock。强保障必须通过隔离工作区或写入网关实现，而不是依赖 AGENTS.md 的约定。[D2 §§11, 13]

## 12. 状态机与受控终态

| 对象 | 主状态 | 必须明确的规则 |
|---|---|---|
| WorkItem | draft → ready → active → verifying → finalizing → accepted | 表示命名工程验收 Profile；业务推进由外部主体命令触发，系统验证 evidence / grant / revision 并记录；blocked 可恢复 |
| Attempt | queued → admitted → running → evidence_ready → succeeded | lost / failed / cancelled 为该次尝试终态；新尝试新 ID |
| AgentRuntime | requested → provisioning → ready ↔ busy → draining → stopped | recovering / lost 需新 generation 或新 Runtime 绑定 |
| HarnessSession binding | unbound → binding → attached → detached / unavailable → retired | detached 不等于终止进程；原生 session 本身可能持久化 |
| Handoff | draft → offered → prepared → committed → completed | rejected / stale / expired / cancelled 不得表示成功；committed 后撤回是补偿性交接 |
| Claim / Lease | requested → granted → releasing → released | denied / expired / revoked 分离；expired token 永不恢复有效 |
| Machine | enrolled → connecting → online ↔ suspect / offline → retired | connectivity 与 trust 独立；trust 可 pending / trusted / quarantined / revoked |
| EffectOperation | prepared → authorized → dispatched → observed → verified | 结果丢失进入 uncertain，先 read-back，不能直接重试非幂等副作用 |

ownership-transfer handoff 的 committed 必须对应同一权威事务中的 owner / generation 切换，并与旧执行者 fencing 配合；目标 prepared 不意味着已获写权。完成后的回转应新建补偿性交接，不能复活旧 lease。

状态机中的 verifying / finalizing 是外部 Agent 选定工程 Profile 的记录状态。Core 只验证命令与状态 guard；Reviewer、repair、Finalizer 的选择和委派由外部 Agent 提交。Provider 只可依据已记录的恢复授权重试原操作，所有派生事件携带 originating command。

一个聚合的状态不应合并连接、信任、任务进度和健康所有维度。`cancel_requested` 先记录意图，再监督实际停止；已有外部效果不可因取消而自动假定回滚。提交终态后重开工作需显式新 cycle / Task revision。

## 13. Lease、Fencing、隔离与调度

租约记录 owner Attempt / Runtime、resource_id、mode、authority incarnation、fencing token、expiry 与 grant reference。数据库事务保证同一资源授予规则；执行资源或 Effect Gateway 必须实际校验 token。[S27]

**TTL 本身不构成互斥证明。** 暂停或分区的旧进程可能继续写。能强制 fencing 的资源拒绝旧 generation；无法 fencing 的共享设备 / 文件目录，必须确认旧执行停止或隔离后才授予新执行者。否则进入 blocked，而不是抢锁。

默认每个并行 Engineer 一个 worktree / sandbox。全局 branch publication、deployment、数据库、device、browser account 等通过受控资源入口；代码目录隔离不能代替共享 GPU、端口、build 输出和 API quota 协调。

资源批量申请采用稳定排序或原子 admission，禁止持有部分资源无限等待。资源队列读取外部主体提交的优先级、deadline 和 endpoint requirements，并确定性应用公平性、并发、fan-out 与预算限制。Endpoint Resolver 只在授权候选集中匹配请求；任务优先级的语义判断与团队构成由外部 Agent 决定。

设备离线只允许安全的已授予工作继续到授权边界，不能保证关机机器仍计算。需要开机能力时使用经过授权验证的 provisioning / 电源控制 Provider；无此能力则明确等待其他可用 endpoint。

## 14. Evidence、Accepted State 与 Finalization

ExecutionReceipt 应包含 task / attempt / runtime / provider 引用、输入 baseline、输出 commit / tree / diff / untracked manifest、测试命令与 exit code、环境 / lockfile / toolchain、产物 digest、源同步状态、实际用量和未解决项。

保留原有 `directly_verified / endpoint_reported / stale / unknown`。进一步记录由谁、在哪个权限边界、对哪个 baseline 观察或复现。Hash 证明内容完整性，不证明报告真实。

外部 Agent 可以采用以下工程验收 Profile。它展示职责协作的一种策略；Core 为其中每个明确命令提供版本、权限、Evidence 与 read-back 校验：

`parallel implementation → sealed candidate baselines → fresh independent review → integration candidate → test integrated baseline → acceptance-ready decision → frozen final surfaces → authorized publication → read-back → postflight → acceptance.commit`

单分支分别通过测试不能证明合并后的版本通过。集成候选变化时，受影响 evidence 失效并重跑。

Acceptance-ready 仅表示候选已满足发布前条件，不等于 WorkItem accepted；需要发布的任务在 read-back / postflight 后才执行 acceptance.commit。无需外部发布的任务可在证据和本地最终表面 seal 后提交接受。

AcceptedStateRevision 记录 accepted_by、policy_version、source / evidence refs、parent_revision、unresolved items 和作用范围。工程师自报 completed 只产生候选结果，不能自行推进 accepted revision。

Fresh context 减少实现叙事对审查者的影响，但本身不证明验证独立或结论正确；高保障 policy 还需区分实现 / 接受权限，并依靠可复现测试与可读回事实。

承担 Finalizer 职责的外部 Agent 在高保障 Profile 下接收 sanitized specification 和最终 evidence；必要安全、迁移、兼容和审计事实保持完整。每个 SurfaceManifest 记录外部 surface owner、输入基线、冻结内容摘要、外部对象引用、实际 read-back digest、postflight 结果。[D1 §§69–72][D2 §§5, 9]

## 15. Failure / Recovery Model

| 故障窗口 | 恢复动作 | 禁止行为 |
|---|---|---|
| UI / MCP client 退出 | 已提交操作继续；外部 Session 消失时保存 pending 状态并等待授权重绑定；新入口恢复 Scope / Task 视图 | 用连接状态推断 Agent 推理仍在运行 |
| Core 提交后、发送前崩溃 | 事务 outbox 重发相同 operation / message ID | 另建 Task 补发 |
| 收件持久化后 ACK 丢失 | 重发、inbox 去重、返回已知 receipt | 再次执行同一效果 |
| Node journal 写入后、spawn ACK 前崩溃 | inspect / adopt 已启动进程或 provider operation | 用 PID 存在作为唯一证明 |
| Harness 崩溃 | Attempt 标记 lost / uncertain；检查 source / effects 后 native resume 或新 context | 自动认为所有改动未发生 |
| 机器重启 | boot_id 更新、旧 runtime binding 失效、journal reconcile | 原进程 ID 自动续任 |
| 网络分区 | 有界重连 / 切路径；隔离任务在有效 grant 内继续；共享写 fail closed | 离线续租全局资源 |
| lease 过期但旧进程还活着 | 强制 fencing；不可 fence 则先隔离 / 确认终止 | 仅等待 TTL 后假定安全 |
| 外部创建 PR 成功、响应丢失 | operation marker / 外部 ID / 内容 read-back 确认 | 盲目再次创建 |
| source baseline 变化 | stale 标记并通知外部 Agent；由其提交新基线、replan / retest 命令 | 静默覆盖或继续引用旧证据 |
| broker / stream 消息缺口 | 从权威事件 / inbox cursor replay；必要时 snapshot | 假定实时 stream 完整 |
| deadline / tool timeout | 区分取消请求、进程状态、效果不确定；按 policy 处理 | 超时即证明工具没执行 |
| Artifact 部分上传 | 临时状态、分片重试、hash 校验后 seal | 半个 blob 当已完成证据 |
| disk full / 数据库不可写 | 不发 durable ACK、backpressure、明确 blocked | 先 ACK 后丢弃 |
| Backend 恢复 / 备份还原 | reconcile domain、workflow、Node、effect refs；失效旧 grants | 宣称备份自动提供零数据损失 |
| 同一 Management Role 的多个外部 Session | Scope / AgentSlot 绑定与版本化命令、单一提交权威 | 绕过 binding / grant / revision 竞争修改 accepted state |
| 凭据撤销 / 信任变化 | 拒绝新操作、撤销 grant、隔离节点、重新授权 | 将安全拒绝当 transport failure 绕过去 |

恢复的“证明”分两层：状态转移 / 事务不变量可以做模型与属性测试；真实 Harness 的进程、权限、工作区和网络恢复必须做端到端故障注入。本 RFC 给出验收合同，不声称已完成后者。

安全性质：旧 owner 不能提交受保护效果；同一逻辑命令不产生重复已接受状态变更；未验证 evidence 不能提升 accepted state。基础设施活性需要可用的授权链路和 provider / Node 进程；工作目标继续推进还需要可运行的外部 Harness Agent、有效凭据、预算及其后续命令。永久分区时保留安全边界。

## 16. Harness Capability Matrix：当前证据与待验证项

D = 官方文档 / 协议或源码支持该能力候选；U = 未完成该部署实例的验证。**本表无 E2E supported 声明。**

| Harness / Surface | headless / spawn | 指定原生会话续接 | 结构化观测 | 任意现有 UI 会话接管 | 本系统跨机器 E2E |
|---|---|---|---|---|---|
| Codex App Server / exec | D | D，thread start / resume | D，turn / item / notifications | U，不能由 thread API 推导任意 UI 接管 | U，需 Node + Driver 验收 |
| Claude Code Agent SDK | D | D，session resume；文件状态另行处理 | D，SDK 消息与事件 | U | U |
| Gemini CLI | D，headless | D，session resume | D，JSON 输出 | U | U |
| Cursor CLI | D，print / headless | D，resume chat | D，json / stream-json；失败可无终止 result | U | U |
| OpenHands Agent Server | D，部署好的 server 内启动 | D，持久 Conversation 路径 | D，API / events | 不作为任意别家 UI 接管能力 | U |
| MCP-only 交互 Harness | 取决于工具 Surface | U | MCP 工具返回只证明映射操作 | U | 后台消费需要另一个获授权的 headless 外部 Harness Agent 或可验证的唤醒绑定 |

依据：[S15][S18][S39]–[S44]。

CapabilityObservation 至少包含：name、confirmed / unavailable / unknown、Machine / Node / Harness / Runtime / credentials scope、版本、direction、probe version、observed_at、expires_at、evidence ref 和失败原因。文档声明是 discovery input，不直接生成某台机器的 confirmed。过期观察回 unknown。负面结果也有重试时间，避免永久粘在 user relay。

建议新增：`agent.invoke_headless`、`agent.consume_packet`、`delivery.durable_inbox`、`delivery.application_receipt`、`runtime.recover_checkpoint`、`source.snapshot.export/import`、`effect.fencing_enforced`。机器 heartbeat 与实际工程 progress heartbeat 分离。

## 17. Security Model

认证：人使用 OIDC；headless enrollment 可采用 device flow；Node 生成自己的密钥，绑定组织、设备与允许项目。短期访问凭据、issuer / audience 校验和 rotation 分别设计。MCP token 不转发成任意上游 token。[S24][S28][S45]

授权：`can_send`、`can_invoke`、`can_read_source`、`can_write_source`、`can_publish`、`can_accept` 分开。Grant 绑定目标机器 / Runtime、Task、资源和预算。有效权限取用户委派、项目策略、本机 owner 策略和 Provider 限制的交集；Control Plane 不得扩大本机 owner 授予的范围。

隔离：不可信仓库、AGENTS.md、测试输出和其他 Agent 消息均不能自我提升为管理命令。源码 / shell 在隔离环境执行；节点控制密钥、云端数据库凭据和发布凭据不得位于 Agent 可读取环境。Prompt injection 的边界由工具权限、egress、sandbox 和 effect gateway 保障，不靠提示词承诺。

租户：所有对象、消息、blob、队列、日志、索引和额度带 tenant scope；tenant 从认证上下文推导，不能信任 payload 的任意 tenant_id。跨项目 / 跨组织访问经显式关系授权。DB RLS 是防御层，不代替应用授权。

攻击面：校验 webhook / artifact URL，防 SSRF；检验真实路径与符号链接；解包防路径穿越；签名 Driver / 升级包并保留回滚；限速、防递归 fan-out、阻断无限自创建 Agent；人工审批绑定动作和版本，结果变化则原批准失效。

“人工接力”不是授权绕行方式。revoked / forbidden / quarantined 不能通过用户复制包转换成已授权执行。

## 18. Local / Hybrid / Cloud / Enterprise

| 部署 | 权威状态与编排 | Source / payload | 关键边界 |
|---|---|---|---|
| Fully Local | 本地 Control Plane + 同一 durable engine + 本地 Node | 本地仓库 / blob | 无 hosted 依赖；本地持久盘损坏的恢复需备份 |
| Hybrid | Hosted metadata / durable operations 或明确定义的本地权威 + cloud mirror | 本地源码；按策略 relay / 上传 | 两种 authority 模式不可混成自动双主 |
| Managed Cloud | Hosted Control Plane + 托管或 BYO execution | 显式托管策略 | 多租户、配额、审计、region / retention |
| Enterprise Self-hosted | 企业自己的 Control Plane、IdP、存储与机器池 | 企业网络 / 自有模型路径 | 与 hosted 同协议、可升级和可导出 |

Control metadata 可最小化为 identity、status、topology、grant、usage 等；这些本身也可能敏感。Collaboration payload 可按项目要求 local-only / encrypted relay / retained。Source / large artifact 默认不因“接入后台”而自动上传。secret 只存 reference，不进协作正文。

采用 payload E2EE 时，外部 Agent 在有解密权限的本地或受信 Harness 环境执行检索后的推理、语义审查和 Finalization。Hosted service 只处理该 Profile 允许的密文与 metadata。密钥丢失、rotation、recovery 和可见 metadata 都是产品合同的一部分。

“协作系统 local-only”不意味着调用云模型时源码不会离开机器。严格不出域需要模型推理路径也满足该政策。

## 19. Commercial Product Model

商业对象：Organization、Membership、Project、Machine / Device、Policy / Credential、Quota / Reservation、Usage、Subscription / Entitlement、Audit、Notification。Project 默认展示现有 Root / Routes，不展示某一 Management Session 作为项目本体。

Web Console 主要回答：当前目标、已接受成果、执行者、任务依赖、源码基线、证据、阻塞原因、等待谁、需要什么授权、已消耗多少和下一步。原始聊天不是主 UI。

Usage ledger 分别记录 provider 原始 token / compute 数据、来源、估算成本、定价版本、实测 / estimated / unknown 和后续 reconciliation；unknown 不填零。预算 admission 在启动推理前；结束后释放预留并结算。支付 webhook 或 provider usage 重复不能造成重复记账。[S29][S30]

建议商业差异化为：Hosted relay / fleet 管理、团队权限、审计与证据保留、独立验收、资源治理、企业部署和 SLA。离线恢复、数据导出和已有项目身份连续性不应被收费状态意外破坏。欠费可以停止新增计算，但不得悄悄删除任务事实或阻止安全收尾 / 数据导出。

供应商商业接入应单独评审。技术上可调用某 CLI / SDK，不能直接推导可复用个人订阅、转售推理或代管所有用户凭据。当前部分官方 SDK 与订阅说明存在不同接入语境，采用哪种授权路径必须按锁定产品条款确认，不在此 RFC 中作一刀切推断。[S46][S47][S48]

## 20. Migration Strategy

1. **Inventory / dry-run。** 读取现有 Root / Route IDs、配置、AGENTS managed blocks、knowledge、coordination、source relationships；生成 owner classification 和差异计划。
2. **Preserve identities。** Project 产品记录引用旧 Root；Route IDs 原样保留；旧 Session IDs 作为历史外部引用。没有新任务 ID 的历史工作可分配新 WorkItem ID，但不能冒充原有 ID。
3. **Import with provenance。** 旧手工记录以 imported / endpoint_reported / unverified 保存；不能因为导入数据库而提升为 verified。保留 `.agents/knowledge/` 内容和相对路径语义。
4. **Separate policy migration。** 升级 schema 不自动启用无人值守、不自动上传源码、不自动 grant 远程执行。启用 runtime Profile、后台权限和数据政策是独立的明确操作。
5. **Migrate transport semantics。** 旧 `message_transport=user_relay` 保存为历史观察；新 desired policy 为 system-managed；current 从当前 probe 解析，必要时创建临时 HumanBridgeIncident。
6. **Cut over one authority。** 在已采用对象上停止旧自由写入路径，或将兼容文件写入转换成带版本领域命令；禁止双向无约束双写。
7. **Validate / rollback。** attach 新管理 Session、保存和校验所有项目-owned 文件、故障恢复、导出 / 还原；记录前后 digest。回滚需 drain runtime、导出新增 durable state，不得简单删库退回旧脚本。

更新 SKILL.md、Root / Route AGENTS 的有界 managed blocks、capability / lifecycle / transport 文档、机制和测试。普通修订不能整文件覆盖用户内容。保留旧 human-readable 入口和协作 packet 的渲染方式。[D1 §§47–49, 57–65]

## 21. End-to-End Reference Scenario

| 阶段 | 系统动作与 durable evidence |
|---|---|
| 1. 用户给目标 | 外部 Management Agent 在 Root Scope 中理解目标、管理 Route，并提交 Goal / WorkItem、scope、预算和权限命令；Core 记录 |
| 2. 选择机器 | 外部 Route Agent 提交目标 AgentSlot 与 endpoint requirements；系统在已注册 Node A / B 中验证 headless、源码、sandbox 和双向 inbox / response |
| 3. 启动异构 Harness | A 使用 Codex Driver，B 使用 Claude SDK Driver；均无原生跨厂商 messaging 也能经 Node 通道协作 |
| 4. 并行实现 | 相同 immutable base、独立 worktree；资源 admission 和 branch publication 权限分离 |
| 5. 用户关闭 UI | Control Plane 持续处理已提交操作；外部 Agent 仍活跃则继续；其 Session 消失则保存状态并等待/恢复获授权的外部绑定 |
| 6. B 的 Harness 崩溃且网络中断 | Attempt 标 lost / uncertain；保留 task、messages、checkpoint 和 source refs；不提示人工搬运 |
| 7. 恢复 | Node 重连 / 重新启动，检查未确认效果，围栏旧 execution；新 Attempt resume 或 fresh reconstruct |
| 8. 丢失 ACK 的消息重发 | 保留同一 message_id；接收 inbox 返回已有 receipt，不重复副作用 |
| 9. 独立 Reviewer | 外部 Route Agent 委派外部 Reviewer；后者使用新上下文和只读权限验证候选结果并提交 evidence |
| 10. 集成 | 受控 integration workspace 合并；对整合后的新 baseline 运行验收 |
| 11. Finalization | 外部 Agent 提交 SurfaceManifest freeze、commit / PR 与 acceptance 命令；系统校验授权、read-back 和 postflight |
| 12. 用户换入口返回 | 按 Root / Route / Task 看到 accepted result、源同步状态、测试、费用和未解决项；原 Session 已不存在也可恢复 |

这是必须执行的验收场景，不是已运行结果。测试应强制关闭各 Harness 自身 multi-agent 依赖，以证明通信来自协作 Runtime 而非偶然的厂商能力。

另设 Human Bridge 反向验收：初始所有授权自动路径被 fixture 明确阻断 → 生成标准人工包 → 新事实到来 → probe 确认 → 自动切回系统链路 → 旧人工包晚到被去重。

## 22. 实施阶段与发布 Gate

| 阶段 | 交付范围 | 必须通过的 Gate |
|---|---|---|
| P0 — Contracts | 已确认 Canonical delta、Scope、外部主体命令、状态机、基础设施恢复合同 | 架构采纳完成；真实实现与环境 conformance 由后续 Gate 证明 |
| P1 — Local durable binding | Core + Durable Operation Provider + Node + MCP / CLI / HTTP；两个异构外部 Harness Driver | 已提交操作恢复、Session 消失/重绑定、Scope / AgentSlot 连续性、真实 Driver conformance |
| P2 — Cross-machine | authenticated outbound channel、machine enrollment、artifact transfer、fencing | 网络分区、ACK 丢失、旧 owner 复活、source stale 与重试全部验证 |
| P3 — Hosted product | 组织权限、项目 Console、审计、usage / quota、通知、backup / restore | 租户隔离、预算限制、撤销、导出和灾备演练 |
| P4 — Ecosystem / scale | A2A gateway、通用 ACP Driver、企业 workspace provider、更多 Harness | 版本协商、滚动升级、长任务迁移、fan-out / backpressure / 公平性压测 |

P1 是完整语义的纵切片，不是把 failure recovery 推到 P4。首批 Harness 候选优先 Codex App Server 和 Claude SDK，是基于文档化编程接口的候选顺序；仍以实际权限和端到端结果决定是否 supported。

建议发布必须展示：支持状态的五层证据、可重现脚本、pin 的版本 / OS / policy、故障注入结果、已知限制及数据保留 / 恢复 Profile。P0 的 schema 校验不能充当 P2 的跨机器证明。

## 23. 扩展能力与运维要求

- 协议 / schema：有界兼容窗口、required extension、schema registry / generated SDK、滚动升级与旧 provider worker process 排空；长期操作保留原 policy / operation 版本或显式迁移。
- 伸缩：按 tenant / authority / task 分片，不把 Root 当全局互斥热点；避免持久化全连接图；事件订阅按 scope 分页和过滤。
- 恢复：domain DB backup、workflow history backup、blob / encryption keys backup 一起测试；明确 ACK durable boundary、RPO / RTO 与单机故障域。
- 数据治理：retention、导出、删除、tombstone、GC、安全审计和加密 key 生命周期；不可把“append-only”解释成无限保存敏感信息。
- 可观察性：链路到 message / task / attempt / baseline / effect 的 correlation；连接健康与真实 progress 分开；记录 relay incident 时长、stuck tasks、recoveries、重复效果阻断和 evidence stale rate。
- Agent 特有风险：循环委派、成本耗尽、低质量重复 repair、恶意 artifact / instructions、共用凭据、上下文污染、错误 acceptance、自报 usage 和 cache poisoning。
- DR 恢复后先查询已有 PR / commit / deployment，处理 uncertain effects，再恢复已提交操作；新的工程行动由外部 Agent 决定。

## 24. 最终验收不变量

1. Root / Route / WorkItem 不随 UI、Harness session、机器或 Provider 更换而换身份。
2. 自动协作可行时，系统不会要求人工转发；新事实触发重新发现与验证。
3. 连接生命周期不决定 Task 生命周期；永久阻塞和临时故障分类明确。
4. 消息、源码访问 / 同步、artifact、runtime control 的权限和能力独立。
5. 消息至少一次送达的重复，不转化成重复的领域提交或未经确认的外部 mutation。
6. 过期 / 撤销 owner 不再拥有受保护效果的提交能力；不可围栏的资源不虚报安全接管。
7. 结果只有经过符合 policy 的 evidence / source / read-back 校验才可接受。
8. Control Plane 与 Node 不对同一领域对象形成失联多主。
9. 任意 supported 声明都有指令、决策、真实机制、不变量验证与代表性端到端证据。
10. 项目资产、知识、权限边界和可导出协作事实不会因架构升级而被破坏。
11. 新 Goal、WorkItem、AgentSlot、委派、沟通对象和接受决定具有可验证的外部主体命令来源；基础设施事件保留原操作 lineage。
12. 外部 Agent Session 消失后，Scope、知识、消息与协作状态持续存在；智能工作由重新绑定的外部 Harness Agent 继续。

**最终定义：外部 Harness Agent 决定如何协作并执行工程工作；Agent Collaboration System 提供 Scope / Identity、Knowledge Boundary、Connectivity、Collaboration State 与 Recovery，使这些外部 Agent 形成长期、可靠、可恢复的工程组织。**


---

# Appendix — Research Source Index

# 来源索引

初始来源快照日期为 2026-09-07；其中 MCP、MCP Tasks、A2A、Temporal、LangGraph 与 ACP 页面于 2026-09-08 重新获取并记录 HTTP 状态、字节数和 SHA-256，见同目录 `evidence-ledger-2026-09-08.json`。外部资料包括官方规范、官方文档、维护者源码、许可证或原始研究。

## 用户提供的设计基线

- **[D1] Agent-Collaboration-System-Canonical-Spec.md**  
  SHA-256: `b3e72592eecf4984d4cee71b68d5cbd0bd7e499c51f596db94de20740231b75c`
- **[D2] taskquay_cross_harness_architecture_cn.md**  
  SHA-256: `e7b35f8c143859d7db4b06328ec92d49517c66e8758550b927aa06cd238c0858`

## 外部研究来源

`latest`、`main` 和产品文档可能变化；实施时必须固定版本 / commit、依赖清单、授权条件与测试证据。此索引没有声称已归档所有外部页面的不可变快照。

### [S01] MCP Specification 2026-07-28

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://modelcontextprotocol.io/specification/2026-07-28>

### [S02] MCP 2026-07-28 release and changelog

来源类型：`official_release`；查阅日期：2026-09-07。

- <https://blog.modelcontextprotocol.io/posts/2026-07-28/>
- <https://modelcontextprotocol.io/specification/2026-07-28/changelog>

### [S03] MCP Tasks extension

来源类型：`normative_extension`；查阅日期：2026-09-07。

- <https://modelcontextprotocol.io/extensions/tasks/overview>

### [S04] A2A specification, latest observed version 1.0.0

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://a2a-protocol.org/latest/specification/>

### [S05] A2A streaming, asynchronous operations and v1 changes

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://a2a-protocol.org/latest/topics/streaming-and-async/>
- <https://github.com/a2aproject/A2A/blob/main/docs/whats-new-v1.md>

### [S06] Agent Client Protocol overview

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://agentclientprotocol.com/protocol/v1/overview>

### [S07] ACP schema and stabilized session resume

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://agentclientprotocol.com/protocol/v1/schema>
- <https://agentclientprotocol.com/announcements/session-resume-stabilized>

### [S08] TaskQuay project README and product boundaries

来源类型：`project_source`；查阅日期：2026-09-07。

- <https://github.com/wrfgup/taskquay>
- <https://raw.githubusercontent.com/wrfgup/taskquay/main/AGENTS.md>

### [S09] TaskQuay execution coordination and agent management

来源类型：`project_source`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/wrfgup/taskquay/main/src/execution-coordinator.ts>
- <https://raw.githubusercontent.com/wrfgup/taskquay/main/src/local-agent-manager.ts>

### [S10] TaskQuay persistence, restart reconciliation and security

来源类型：`project_source`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/wrfgup/taskquay/main/src/local-agent-store.ts>
- <https://raw.githubusercontent.com/wrfgup/taskquay/main/docs/security.md>

### [S11] Temporal workflow execution, determinism and deployment

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.temporal.io/workflows>
- <https://docs.temporal.io/workflow-definition>
- <https://docs.temporal.io/self-hosted-guide/deployment>

### [S12] Temporal Activities and idempotency

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.temporal.io/activity-definition>
- <https://temporal.io/blog/idempotency-and-durable-execution>

### [S13] DBOS architecture and Python programming model

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.dbos.dev/architecture>
- <https://docs.dbos.dev/python/programming-guide>

### [S14] Restate concepts and deployment

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.restate.dev/foundations/key-concepts>
- <https://docs.restate.dev/server/overview>

### [S15] OpenHands SDK, Conversation and Agent Server architecture

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.openhands.dev/sdk/arch/overview>
- <https://docs.openhands.dev/sdk/arch/conversation>
- <https://docs.openhands.dev/sdk/guides/agent-server/overview>

### [S16] Coder control plane, provisioning and workspace architecture

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://coder.com/docs/admin/infrastructure/architecture>
- <https://github.com/coder/coder>

### [S17] Anthropic Managed Agents: session, harness and sandbox separation

来源类型：`official_engineering`；查阅日期：2026-09-07。

- <https://www.anthropic.com/engineering/managed-agents>

### [S18] OpenAI: Unlocking the Codex harness

来源类型：`official_engineering`；查阅日期：2026-09-07。

- <https://openai.com/index/unlocking-the-codex-harness/>

### [S19] LangGraph persistence and checkpoint semantics

来源类型：`official_documentation`；查阅日期：2026-09-07。

研究分类：已审阅的外部 Agent 技术背景；属于外部 Harness 的 reasoning / orchestration 边界，不构成 Collaboration System 的组件或实现依赖。保留原查阅日期和来源以支持研究溯源。

- <https://docs.langchain.com/oss/python/langgraph/persistence>
- <https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph>

### [S20] NATS JetStream and durable consumers

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.nats.io/concepts/jetstream>
- <https://docs.nats.io/learn/jetstream/pull-consumers>

### [S21] PostgreSQL LISTEN / NOTIFY

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://www.postgresql.org/docs/current/sql-listen.html>
- <https://www.postgresql.org/docs/current/sql-notify.html>

### [S22] Tailscale direct and relay connection paths

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://tailscale.com/docs/reference/connection-types>
- <https://tailscale.com/docs/features/peer-relay>

### [S23] Amazon S3 conditional writes

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
- <https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html>

### [S24] Keycloak OIDC and device authorization

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://www.keycloak.org/securing-apps/oidc-layers>

### [S25] OPA and OpenFGA authorization models

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://openpolicyagent.org/docs>
- <https://openpolicyagent.org/docs/management-bundles>
- <https://openfga.dev/docs/concepts>
- <https://openfga.dev/docs/modeling/conditions>

### [S26] OpenBao secret leases and SPIRE workload identities

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://openbao.org/docs/concepts/lease/>
- <https://spiffe.io/docs/latest/spire-about/spire-concepts/>

### [S27] etcd lease and fencing analysis

来源类型：`primary_analysis`；查阅日期：2026-09-07。

- <https://etcd.io/blog/2020/jepsen-343-results/>
- <https://jepsen.io/analyses/etcd-3.4.3>

### [S28] MCP authorization security considerations

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations>

### [S29] OpenTelemetry GenAI observability

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://opentelemetry.io/blog/2026/genai-observability/>
- <https://github.com/open-telemetry/semantic-conventions-genai>

### [S30] Stripe usage metering

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.stripe.com/billing/subscriptions/usage-based/recording-usage>

### [S31] Bazel Remote Execution API, CAS and remote caching

来源类型：`project_source`；查阅日期：2026-09-07。

- <https://github.com/bazelbuild/remote-apis>
- <https://github.com/bazelbuild/remote-apis/blob/main/build/bazel/remote/execution/v2/remote_execution.proto>
- <https://bazel.build/remote/caching>

### [S32] SQLite atomic commit and hardware assumptions

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://www.sqlite.org/atomiccommit.html>

### [S33] Temporal license, observed MIT

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/temporalio/temporal/main/LICENSE>

### [S34] DBOS Python license, observed MIT

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/LICENSE>

### [S35] OpenHands SDK license, observed MIT

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/OpenHands/software-agent-sdk/main/LICENSE>

### [S36] NATS Server license, observed Apache-2.0

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/nats-io/nats-server/main/LICENSE>

### [S37] Coder principal license, observed AGPL-3.0

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://raw.githubusercontent.com/coder/coder/main/LICENSE>

### [S38] Restate license and additional use grant, observed BSL 1.1

来源类型：`license_text`；查阅日期：2026-09-07。

- <https://github.com/restatedev/restate/blob/main/LICENSE>

### [S39] Codex App Server API

来源类型：`project_source`；查阅日期：2026-09-07。

- <https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md>

### [S40] Claude Agent SDK sessions and hosting

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://code.claude.com/docs/en/agent-sdk/sessions>
- <https://code.claude.com/docs/en/agent-sdk/hosting>

### [S41] Gemini CLI headless execution and sessions

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://geminicli.com/docs/cli/headless/>
- <https://geminicli.com/docs/cli/session-management/>

### [S42] Cursor CLI headless, resume and structured output

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://cursor.com/docs/cli/headless>
- <https://cursor.com/docs/cli/reference/parameters>
- <https://cursor.com/docs/cli/reference/output-format>

### [S43] OpenHands conversation persistence

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://docs.openhands.dev/sdk/guides/convo-persistence>

### [S44] ACP optional session capabilities

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://agentclientprotocol.com/protocol/v1/schema>

### [S45] MCP authorization

来源类型：`normative_protocol`；查阅日期：2026-09-07。

- <https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization>

### [S46] Claude Agent SDK overview and access context

来源类型：`official_documentation`；查阅日期：2026-09-07。

- <https://code.claude.com/docs/en/agent-sdk/overview>

### [S47] Claude plan support for Agent SDK usage

来源类型：`official_product_policy`；查阅日期：2026-09-07。

- <https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan>

### [S48] Claude Code legal and compliance

来源类型：`official_product_policy`；查阅日期：2026-09-07。

- <https://code.claude.com/docs/en/legal-and-compliance>
