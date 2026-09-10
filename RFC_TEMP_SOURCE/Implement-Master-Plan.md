# Agent Collaboration Runtime Implementation Master Plan

## 1. 计划状态与实施基线

本计划把当前研究包推进到：

```text
Pre-P0：已完成决策收敛
P0：已完成合同冻结
状态：Implementation-ready Baseline
下一工程阶段：P1 Local Durable Vertical Slice
```

这里的“已完成”表示：

- 技术架构已经完成收敛；
- 12 项 ADR 已被赋予明确状态；
- Canonical Delta 已明确；
- P1 的目标 Profile、技术栈、边界、权限和回滚方式已经确定；
- 协议、状态机、权威存储、故障模型、迁移路线和验收映射已经冻结为实施输入。

它不表示：

- Runtime 代码已经实现；
- 远程机器已经完成 P1 部署；
- 两个真实 Harness 已经通过跨机器 E2E；
- P1 或 P2 的故障注入已经执行；
- 当前系统已经获得产品级 `supported` 状态。

当前仓库事实基线来自：

- [Architecture-RFC-v2.zh-CN.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/Architecture-RFC-v2.zh-CN.md:1)
- [architecture-decisions.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/architecture-decisions.json:1)
- [deliverables.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/deliverables.json:1)
- [validation-report.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/validation-report.md:1)
- [capability-matrix.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/capability-matrix.md:1)

当前 `Agent-collaboration` 仍以 setup-only Skill、`AGENTS.md`、`.agents/` 和文件协议为主。Runtime 工程将在保留既有 setup/runtime 边界的前提下新增独立的 Runtime 模块，不能把长期 Task、Event、Lease 或 Session Recovery 状态直接塞入现有 Skill manifest、Root registry 或 Source State 文件。

本计划交由软件团队实施。计划中的 Management、Route、Engineer、Reviewer、Specialist、Finalizer 都是由外部 Harness 实例承担的长期角色；其推理、规划、任务拆分、委派和下一步决策由相应外部 Agent 完成。Collaboration System 横向提供身份、连续性、连接和协作状态基础设施。后文的阶段任务是软件团队采用的工程路线，任务依赖和角色分工由外部主体提交、维护和执行。

## 2. Pre-P0 / P0 决策冻结结果

### 2.1 12 项 ADR 的正式状态

| ADR | 状态 | 冻结决策 | 范围与后果 | 迁移/验证要求 | 复议条件 |
|---|---|---|---|---|---|
| ADR-001 Domain-first runtime | `accepted` | Collaboration Core 拥有 Scope、Root、Route、AgentSlot、WorkItem、Message、Lease、Evidence、AcceptedState 的持久化、验证和连续性合同 | 外部 Agent 提交协作决策；Core 执行确定性命令、状态和证据合同 | P1 先实现主体来源、领域命令和状态转换，再实现 Driver | 仅当替代方案完整保留身份、协作连续性、证据和安全边界时复议 |
| ADR-002 Shared application core | `accepted` | MCP、CLI、HTTP/RPC、Web UI 共用相同的 schema、授权和领域服务 | 多个 Surface 不得形成多个业务状态机 | P1 对三种 Surface 运行同一组状态和权限测试 | 新 Surface 只能增加映射，不能复制领域语义 |
| ADR-003 Durable operation provider | `accepted_with_conditions` | Temporal 为首个 Durable Operation 参考 Provider；DBOS/Restate 是同一操作合同下的备选 Provider | Provider 处理已提交 operation 的 timer、retry、wait、outbox、reconciliation、lease/effect 与生命周期恢复；provider worker 是基础设施进程 | P1 测量资源占用、重启恢复、版本升级和因果来源保留；备选 Provider 通过同一 conformance 后才可替换 | 固定环境实测不能满足部署或恢复 Gate 时复议 Provider；操作合同继续适用 |
| ADR-004 Single authoritative domain writer | `accepted` | PostgreSQL 是 Task、Lease、AcceptedState、Approval、Inbox、Outbox 的领域权威 | Temporal History、Node Journal、Markdown 文件不形成竞争性主库 | 所有领域命令使用事务、CAS、事件、Outbox 和幂等记录 | 只允许按明确子域进行权威拆分，不接受失联多主 |
| ADR-005 Stable collaborator identity | `accepted` | Scope 与 AgentSlot 构成长期身份；ScopeBinding 声明职责和授权；Runtime、Session、Harness、Machine、目录位置均可重新绑定 | Root、Route、Engineer Source Scope 各自拥有独立知识与协作状态；目录和 Session ID 是定位信息 | P1 验证跨 Session/Harness 重新绑定、目录迁移、Scope 读写隔离和身份连续性 | 任何 Provider 引入都必须保留 Scope/AgentSlot 身份及知识归属 |
| ADR-006 Dynamic transport recovery | `accepted_with_conditions` | desired policy 为 `system_managed_e2e`；Human Bridge 是临时恢复事件；Provider 切换保留同一个 `message_id` | 现有 User Relay 语义需要显式 Canonical migration，旧项目保留兼容读取 | P2 验证动态 Probe、Human Bridge、自动回切、晚到包去重 | 若新链路改变权限、数据驻留或成本边界，必须重新走策略迁移 |
| ADR-007 Fencing and effect safety | `accepted_with_conditions` | Lease 使用 generation、expiry 和 fencing token；受保护副作用必须在 Effect Gateway 校验 fencing | 无法 fencing 的共享资源只有在隔离或确认旧 Owner 终止后才能重新分配 | P1 用 fake resource 验证；P2 对真实共享资源和旧 Owner 复活做故障注入 | 不因追求可用性而降低旧 Owner 隔离要求 |
| ADR-008 Evidence-based acceptance | `accepted` | 由获授权的外部 Agent/User 提交 acceptance 命令，Core 校验基线、证据、策略版本、授权和 read-back 后提交 AcceptedState | Review 策略和接受判断由外部主体负责；系统验证显式选择的验收合同 | P1 验证 candidate、acceptance-ready、accepted、published 分离及来源完整性 | 风险政策可以版本化，接受状态必须保留其判断主体和事实证据 |
| ADR-009 Data minimization and deployment profiles | `accepted_with_conditions` | 支持 Local、Hybrid、Managed Cloud、Enterprise Self-hosted；P1 采用 Local-first；Hosted 为后续显式 Profile | Source、Payload、Artifact、Control Metadata 逐类定义上云和保留政策 | P1 禁止未经授权的源码上传；P2 固定跨机 Payload policy；P3 做租户和驻留验证 | 任何新数据外传路径都必须成为独立策略迁移 |
| ADR-010 Non-destructive migration | `accepted` | 保留 Root、Route、AGENTS 用户内容、`.agents/knowledge/`、现有 Git 历史和外部 Session 引用 | Runtime adoption 采用 import/provenance，不覆盖旧项目事实 | P1 先做只读 inventory、dry-run、导出、回滚演练 | 只有明确授权的迁移操作才能改变既有项目语义 |
| ADR-011 Capability truth | `accepted` | Capability Observation 必须带 Machine、Node、Harness、Version、Direction、Credential Scope、时间和 Evidence | Documentation 只能成为 discovery input；`unknown` 不会自动提升为 confirmed | P1 做 fake/真实 Driver conformance；P2 做跨机 capability expiry/revoke | 任何 Harness、OS、版本、权限或拓扑改变都触发重验证 |
| ADR-012 Billing integration boundary | `accepted_with_conditions` | 自有 Usage/Budget Ledger；支付、订阅和发票基础设施采用集成方式 | Raw、Estimated、Reconciled、Unknown Usage 分开记录；Unknown 不计为零 | P3 才进入真实 Billing；P1/P2 只做本地 usage ledger | 供应商条款或商业模型变化时重新审查，不影响 Core 语义 |

### 2.2 Canonical Delta

下列变化作为新 Runtime 设计的兼容迁移合同：

| 现有 Canonical 语义 | 新 Runtime 语义 | 迁移方式 |
|---|---|---|
| User Relay 是正常支持的独立 Transport | desired policy 为系统管理的 E2E；Human Bridge 是临时恢复状态 | 保留旧配置读取；运行时生成当前 Binding；能力恢复后自动重新解析 |
| 项目资产和 Harness Runtime 承担正常协作 | 外部 Harness 持续运行 Agent；Durable Operation Provider 和 Node 保存并恢复已经授权提交的基础设施操作 | 启用 Runtime Profile 后导入操作来源、Scope 和绑定；外部 Session 消失时保留待办状态 |
| Capability Observation 主要属于本地 Session | 可以上报带范围、版本、时间和证据的 projection | 本地仍是事实来源；Control Plane 只保存有期限的投影 |
| Transport 改变通常是配置迁移 | 不改变权限、驻留和成本边界的 Provider 切换可作为运行时决策 | 改变信任域、源码位置、数据外传或费用的切换仍需策略迁移 |
| 只有在证据不足时才考虑 Durable Workflow | 跨机重试、持久等待、未完成投递和 uncertain effect 使用 Durable Operation Provider | Provider history 关联原始命令、operation 与授权；领域状态继续由 Core 提交 |
| Management Agent 负责持续发起每一步调用 | Management、Route、Engineer 均为外部 Harness Agent；Scope、AGENTS.md、知识与协作状态维持角色连续性 | 导入长期 Scope/AgentSlot；新 Session 通过明确命令重新绑定并恢复角色上下文 |
| 管理 Workspace、Route 与 Source 分别保存项目状态 | Root Scope、Route Scope、Engineer Source Scope 独立持久化并由显式 SourceBinding 关联 | 导入现有目录与知识引用；源码目录可保持在独立机器或工作区 |

Canonical Delta 的正式实现顺序为：

```text
保留旧读取兼容
    ↓
新增 Runtime domain projection
    ↓
新增明确的 command adapter
    ↓
导入旧项目 identity / knowledge / handoff
    ↓
关闭旧自由写入路径
    ↓
按项目逐步切换 Runtime authority
```

既有 `Agent-collaboration` 项目不会因为 Runtime 代码进入仓库就自动改变行为。

### 2.3 P1 Implementation Authorization Baseline

当前研发默认授权范围冻结为：

```yaml
repository:
  local_management_repo: D:/Chatgpt/Agent-collaboration
  primary_execution_machine: 1302-1
  remote_project: /home/changgeng/Agent-collaboration
  formal_source_of_truth: GitHub remote

allowed:
  - repository inspection
  - remote source modification within Agent-collaboration
  - Git branches and worktrees
  - local development dependencies
  - local PostgreSQL
  - local Temporal or selected durable-engine experiment
  - Machine Node and Runtime Driver experiments
  - deterministic fake providers
  - fault injection in disposable development fixtures
  - tests and benchmarks
  - SSH transfer of temporary logs, fixtures and evidence bundles
  - GitHub branch, commit and push operations within this project

disallowed_without_new_authorization:
  - production deployment
  - unrelated repositories
  - new external accounts
  - new paid infrastructure
  - unapproved credentials
  - source or chat upload outside the selected data policy
  - destructive Git history rewrite
  - production database mutation
  - uncontrolled machine enrollment
  - broad administrator privileges
  - public release beyond the approved profile
```

P1 默认不使用生产凭据，不创建真实外部 PR、部署或生产数据变更。Effect Gateway 使用 deterministic fake provider 或 disposable test endpoint。

上述机器与目录是本计划的授权执行目标。软件团队在 P1 的第一个执行任务中锁定实际环境基线：

```text
1302-1 可达
→ /home/changgeng/Agent-collaboration 存在
→ Git remote 指向预期 GitHub 仓库
→ 分支、HEAD、工作树和权限可读
→ 远程 Codex 能在该目录运行
```

这是一项执行前事实核验，不改变 P1 的架构决定。

## 3. 目标系统架构

### 3.1 外部 Agent 组织与横向基础设施

产品组织采用四层结构：

```text
User
  ↓
External Root / Management Agent · Product Lead
  ├── External Route A Agent
  │     └── External Engineer Agents
  ├── External Route B Agent
  │     └── External Engineer Agents
  └── External Route C Agent
        └── External Engineer Agents
```

Reviewer、Specialist 和 Finalizer 是外部 Agent 根据任务安排的职责，可由获授权的独立 AgentSlot 或现有 AgentSlot 承担。组织关系描述长期责任和汇报；消息关系是外部 Agent 按需发起的有向关系，可以跨 Route、跨角色和跨机器。

每一层外部 Agent 都可以调用同一套横向基础设施：

```text
External Harness Agent / User / Operator
                  │ explicit commands and queries
           MCP / CLI / HTTP API
                  │
   Collaboration Application Core
     Scope / Identity / Policy / CAS
     WorkItem / Message / Lease
     Evidence / AcceptedState / Handoff
                  │
     PostgreSQL Domain Authority
     Events / Inbox / Outbox / Dedup
                  │ submitted operation
     Durable Operation Provider
     timer / retry / wait / reconciliation
                  │
     Transport and Endpoint Resolver
     address / delivery / activation / receipt
                  │ authenticated Node channel
     Machine Collaboration Node
     journal / process lifecycle / capability probe
                  │
     Runtime Driver · ACP / Native API / CLI
                  │
     External Harness Session / Agent
```

Harness 负责模型、上下文、推理、规划、工具执行和其内部协作机制。Collaboration System 负责外部 Agent 身份、连续性、连接、持久状态和确定性基础设施协调。Provider、Node 与 Driver 的动作必须属于已经提交的命令或其已授权恢复范围；团队构成、任务拆分、Review 策略和下一步判断属于外部 Agent。

Node 的进程控制器只检查、启动、停止、读取或恢复受管外部进程。Provider 的 worker process 只执行 timer、retry、wait、outbox 和 reconciliation。系统对外部 Agent 的模型上下文保存引用和授权读取边界，推理执行始终发生在相应 Harness 中。

Source、Artifact 和 Effect 作为独立边界连接到 Core/Node：

```text
Source Provider
Artifact Provider
Effect Gateway
```

这三个边界不能因为使用相同 Node 或相同 Harness 而合并。

### 3.2 长期身份模型

| 对象 | 生命周期 | 作用 |
|---|---|---|
| Organization / User / ServicePrincipal | 长期 | 账户、成员和服务身份 |
| CollaborationRoot | 长期 | 一个协作世界的治理、发现和共享不变量 |
| Project | 长期 | 产品视图、成员、预算和部署 Profile |
| Route | 长期 | 一条开发路线的目标、知识、决策和 open loops |
| Scope | 长期 | Root、Route、Engineer Source 的身份、目标、约束、知识与协作状态边界 |
| ScopeBinding | 可版本化 | Scope、AgentSlot、声明性角色、权限和有效期的绑定 |
| AgentRole | 长期 | Management、Route、Engineer、Reviewer、Finalizer 等声明性职责元数据 |
| AgentSlot | 长期 | 外部 Agent 所承担的可寻址协作者身份，与长期 Scope 绑定 |
| WorkItem | 长期 | 独立于连接和 Session 的可验收工作单位 |
| ExecutionAttempt | 每次尝试 | 一次具体的运行尝试；重试建立新 Attempt |
| AgentRuntime | 可替换 | 外部 Harness 中某次 Agent 运行实例的生命周期投影 |
| HarnessSessionBinding | 可替换 | Provider Session 的绑定和生命周期 |
| Machine / Node / Endpoint | 长期/可替换 | 机器、机器侧服务和当前执行端点 |
| CommunicationBinding | 可变 | 两个 AgentSlot 之间的有向通信关系 |
| Message / DeliveryAttempt / Receipt | Message 长期，Attempt 可变 | 逻辑消息、传输尝试和分层确认 |
| Resource / Claim / Lease | 按资源 | 独占资源、持有权和 fencing |
| SourceBaseline | 按基线 | Repo、commit/tree、dirty state、环境和证据 |
| Artifact / Evidence / ExecutionReceipt | 按结果 | 字节、主张和实际执行回执 |
| AcceptedStateRevision | 不可变版本 | 被正式接受的工程状态 |
| SurfaceManifest | 按最终表面 | commit、PR、handoff、报告等用户可见结果 |
| PolicyGrant / ApprovalRequest | 按授权 | 能力、范围、预算和需要人决策的事项 |
| Event / UsageEvent / AuditEvent | 长期但有保留政策 | 领域事实、用量和审计 |

稳定 AgentSlot 与 Runtime 的关系：

```text
Role + Scope Identity + Durable Knowledge + Collaboration State
    ↓
ScopeBinding / AgentSlot
    ↓
AgentRuntime
    ↓
Machine / Node
    ↓
Runtime Driver
    ↓
Harness Session
    ↓
External Agent Process
```

当 Harness Session 结束时，系统保留：

```text
Scope / ScopeBinding / AgentSlot
AGENTS.md and durable knowledge references
WorkItem
AcceptedState
Message identity
Evidence
Checkpoint
```

外部主体提交重新绑定命令，或先前授权的恢复 operation 在有效范围内继续后，可以建立：

```text
新的 AgentRuntime
新的 HarnessSessionBinding
新的 ExecutionAttempt
```

### 3.3 Scope、目录与知识合同

```yaml
Scope:
  scope_id:
  kind: root | route | engineer_source
  parent_scope_id:
  identity_ref:
  knowledge_refs:
  policy_refs:
  source_binding_ref:
  collaboration_state_ref:
  created_by:
  created_at:

ScopeBinding:
  binding_id:
  scope_id:
  agent_slot_id:
  role:
  authority:
  valid_from:
  valid_until:
  status:
```

`scope_id` 是持久身份，目录路径是带 Machine/Node 定位的可替换位置。迁移目录时记录位置版本、来源、授权和 read-back；Shell 当前目录或同名文件不能自行建立身份。`ScopeBinding` 绑定外部 AgentSlot 与职责、授权，`HarnessSessionBinding` 单独绑定具体 Session。

| Scope | 主要内容 | Source 默认边界 |
|---|---|---|
| Root | 产品目标、Route 关系、跨 Route 约束、里程碑、产品级 AcceptedState | 通过 Route 状态、汇报和 Evidence 获取工程事实；按需授予源码读取 |
| Route | 一条长期开发线的目标、架构决策、知识、任务和接受状态 | 通过显式 SourceBinding 读取相关 SourceBaseline；写入能力单独授予 |
| Engineer Source | 工程职责、Repository/worktree 定位、测试、构建和工程 Evidence | 在获授权 Source Workspace 中执行，并受 Lease/Fencing 限制 |

```text
Management Workspace
  Root Scope: AGENTS.md + durable knowledge + collaboration state
  Route A Scope: AGENTS.md + durable knowledge + collaboration state
  Route B Scope: AGENTS.md + durable knowledge + collaboration state

Source Workspace A: repository/worktree + Engineer Scope
Source Workspace B: repository/worktree + Engineer Scope
```

管理目录和源码目录通过 SourceBinding 关联；源码可以位于独立目录和机器。多个工程角色共享 Repository 时各自保留 AgentSlot/ScopeBinding、授权和资源 Lease，按并发要求使用独立 worktree。Scope 的层级与源码物理嵌套、消息通信路径分别维护。

Scope 的知识引用指向对应 `AGENTS.md`、durable knowledge 与接受状态。知识内容按所属 Scope 的版本和写入权限更新；Node journal 保存操作记录，PostgreSQL 保存协作领域状态，二者通过引用和 revision 与知识协同。重新绑定流程验证 Scope、Grant、知识版本和 SourceBaseline，再把授权上下文交给外部 Harness。

### 3.4 职责边界不变量

```text
外部 Agent 决定：
  是否创建或调整 Route
  是否创建、拆分或结束 WorkItem
  是否建立 Agent 之间的协作关系
  是否委派 Engineer、Reviewer 或 Specialist
  是否发送消息以及下一步做什么
  是否请求交接、资源或外部效果
  是否提交 Review、Acceptance 或 Finalization 判断

Collaboration System 提供：
  Scope/AgentSlot 持久身份和寻址
  Session/Runtime/Machine 绑定与重新绑定
  Message、Inbox、Outbox、Receipt 和 Transport
  已提交操作的排队、重试、等待、恢复和对账
  Lease、Fencing、Capability、Evidence 和 AcceptedState 合同
  Source/Artifact/Effect 的授权边界和 read-back
```

系统不会根据状态变化推断团队构成、自动生成 Agent、自动拆分目标、自动安排 Review，也不会在外部 Agent Session 消失后隐含创建新的智能主体。没有可运行的外部 Agent 时，已持久化的 WorkItem、Message、Binding 或 operation 进入 `waiting`、`pending` 或 `blocked`，直到新的外部主体提交有效命令。

## 4. 核心合同

### 4.1 CommandEnvelope

所有改变领域状态的 Surface 都调用统一命令外壳：

```yaml
schema_version:
command_id:
command_type:
idempotency_key:
tenant_id:
authority_id:
authority_incarnation:
principal_ref:
grant_ref:
target:
  kind:
  id:
  expected_revision:
issued_at:
deadline:
payload:
```

Core 在一个领域事务中执行：

```text
derive authenticated principal
→ verify grant
→ verify tenant / authority
→ compare expected_revision
→ validate payload
→ apply state transition
→ append domain event
→ append outbox item
→ append dedup result
→ commit
```

事务提交后才返回：

```text
accepted_by_authority
```

`grant_ref` 只是引用。调用者自行填写它不会获得权限。

### 4.2 Collaboration Packet

逻辑协作包保持与 Transport 无关：

```yaml
schema_version:
message_id:
type:
correlation_id:
causation_id:
in_reply_to:
supersedes:
created_at:
deadline:

project_id:
root_id:
route_id:
task_id:

sender:
  agent_slot_id:
  runtime_id:

target:
  agent_slot_id:

authority:
  authority_id:
  authority_incarnation:
  grant_ref:
  permitted_scope:

task:
  goal:
  accepted_state:
    revision_ref:
    summary:
  request:
  acceptance_criteria:
  constraints:

source:
  relationship:
  baseline_refs:
  evidence_refs:

knowledge:
  references:
  inline_context:

artifacts:

context_policy:
  warm_compatible | fresh | sanitized_finalization

response_contract:
  expected_output:
  required_evidence:
  unresolved_questions:
```

Packet 只包含接收者行动所需的最小充分上下文，不复制完整聊天历史。

### 4.3 Message 与 DeliveryAttempt

逻辑消息身份保持稳定：

```text
message_id
correlation_id
causation_id
task_id
accepted_revision
sender_agent_slot
target_agent_slot
```

Provider 切换只创建新的 DeliveryAttempt：

```text
DeliveryAttempt
  provider
  connection
  attempt_id
  retry_count
  result
  observed_at
```

消息状态应分层：

```text
accepted_by_authority
→ target_inbox_committed
→ runtime_dispatched
→ runtime_acknowledged
→ response_received
```

各层缺失时保持 `unknown`。

以下事件不能自动表示任务完成：

```text
HTTP 200
MCP tool success
broker ACK
CLI exit code 0
PTY output
Harness self-report
```

### 4.4 Transport Resolver

每条 AgentSlot 到 AgentSlot 的 CommunicationBinding 记录：

```yaml
desired_policy: system_managed_e2e
current_provider:
  native
  node_relay
  backend_relay
  peer
  human_bridge
  unavailable

requirements:
  durable_delivery:
  observable_receipt:
  data_policy:
  wake:

selected_provider:
selection_revision:
observed_capability_refs:
fallback_incident_ref:
recheck_after:
```

解析顺序：

```text
resolve AgentSlot
→ resolve target address
→ verify send
→ verify inbox commit
→ verify consume / invoke
→ verify response path
→ verify permission and data policy
→ execute challenge
→ select DeliveryPlan
```

DeliveryPlan 分开描述：

```text
AddressingProvider
MessageProvider
ActivationProvider
ReceiptProvider
AuthorizationScope
DataPolicy
```

消息可送达不代表目标 Agent 可以被唤醒；网络可达不代表 Agent 具有执行权限。

Human Bridge 只有在以下条件同时成立时建立：

```text
需要跨 Agent 协作
→ 已检查授权的自动路径
→ 已尝试 retry/reconnect/resubscribe
→ 已尝试切换 Provider/Endpoint/Runtime
→ 仍存在真实硬阻塞
→ Task 必须继续
→ 人工桥接不会绕过授权和数据政策
```

新能力、机器重连、Harness 版本变化、凭据变化或用户新事实会触发重新 Probe。

### 4.5 Durable Semantics

采用以下语义：

```text
Task durable
Attempt replaceable
Session replaceable
Connection ephemeral
Node journal local
Domain authority single-writer
Message delivery at-least-once
Domain mutation idempotent
External effect outcome may be uncertain
```

外部副作用使用：

```text
operation_id
idempotency_key
attempt
owner_epoch
expected_input_hash
external_reference
reconciliation_status
```

系统不对无法证明的外部动作宣称 exactly-once。

### 4.6 Lease 与 Fencing

Lease 至少包含：

```yaml
resource_id:
owner_attempt_id:
owner_runtime_id:
authority_incarnation:
generation:
fencing_token:
expires_at:
grant_ref:
mode:
```

执行层和 Effect Gateway 必须校验：

```text
authority_incarnation
generation
fencing_token
deadline
grant
```

TTL 只表示授权期限，不证明旧进程已停止。

对于无法 fencing 的目录、设备、数据库、GPU 或浏览器账号：

```text
旧 Owner 未确认终止
→ 资源不重新分配
→ Task 进入 blocked
```

### 4.7 AcceptedState 与 Finalization

采用以下流水线：

```text
parallel implementation
→ sealed candidate baselines
→ fresh independent review
→ integration candidate
→ integrated baseline tests
→ acceptance-ready decision
→ frozen surface manifests
→ authorized publication
→ actual read-back
→ postflight
→ AcceptedStateRevision commit
```

必须区分：

```text
candidate
acceptance-ready
accepted
published
```

Finalizer 从：

```text
sanitized specification
+
accepted state
+
final evidence
+
actual read-back
```

生成：

- commit message；
- PR body；
- handoff；
- release note；
- user-facing summary。

## 5. P1–P4 工程实施路线

### P1 — Local Durable Vertical Slice

P1 是真正开始编写 Runtime 的阶段，目标是在 `1302-1` 上形成一个单机、可恢复、语义完整的 Runtime Profile。

P1 默认部署：

```text
远程机器：1302-1
远程项目：/home/changgeng/Agent-collaboration
运行位置：远程 Linux
本机角色：外部 Management Agent / Product Lead / Review
正式同步：GitHub
临时传输：SSH
```

P1 采用：

```text
TypeScript / Node Runtime
pnpm workspace
PostgreSQL
Temporal reference provider
SQLite Node journal
MCP + CLI + versioned HTTP API
Codex App Server Driver
Claude Agent SDK Driver
deterministic fake Driver
local fake Effect Gateway
```

Node 版本、pnpm 版本、Temporal 发行版本、数据库版本和两个 Harness Driver 版本在 P1-00 远程预检中固定；预检只允许锁定版本，不允许把当前未验证版本直接写成支持矩阵。

建议代码结构：

```text
runtime/
  package.json
  pnpm-workspace.yaml
  packages/
    domain/
    protocol/
    control-plane/
    persistence-postgres/
    durable-execution-temporal/
    node/
    node-journal/
    driver-sdk/
    driver-fake/
    driver-codex/
    driver-claude/
    surface-http/
    surface-mcp/
    surface-cli/
    source-provider/
    artifact-provider/
    effect-gateway/
    capability/
    conformance/
    observability/
  migrations/
  fixtures/
  tests/
    unit/
    integration/
    recovery/
    contract/
  docs/
    runbooks/
    provider-conformance/
```

P1 工作流：

| Workstream | 主要 Epic | 交付物 | 依赖 | 可并行工作 | 测试/故障注入 | 退出证据 |
|---|---|---|---|---|---|---|
| P1-00 环境预检 | 远程项目、Git、Node、pnpm、PostgreSQL、Temporal、Harness inventory | `P1-ENV-BASELINE` | P0 Authorization | 可与 P1-01 设计并行 | 远程路径、origin、权限、版本、工作树 | 远程环境清单、commit、版本和权限摘要 |
| P1-01 Runtime scaffold | `runtime/` workspace 和独立 package boundary | Runtime package skeleton、CI、lockfile | P1-00 | 与 P1-02/P1-03 并行 | install、typecheck、lint、minimal boot | 固定依赖、SBOM、可重复启动 |
| P1-02 Domain Core | Root/Route/AgentSlot/WorkItem/Attempt/Lease/AcceptedState | Domain types、commands、guards、events | P0 contracts | 与 P1-03/P1-04 并行 | state transition、CAS、invalid command | 领域测试和状态机覆盖 |
| P1-03 Protocol | CommandEnvelope、Packet、Receipt、CapabilityObservation | schema v0、generated validators | P0 schemas | 与 P1-02/P1-04 并行 | 正例、反例、未知字段、幂等冲突 | schema fixture PASS |
| P1-04 Persistence | PostgreSQL schema、事务、events、inbox/outbox、dedup | migration、repository、transaction tests | P1-02/P1-03 | 与 P1-05 并行 | crash after commit、duplicate command、lost ACK | domain authority 和 outbox 证据 |
| P1-05 Durable operation adapter | Temporal operation adapter、版本和 retry policy | submitted-operation definitions、provider process、reconciliation | P1-04 | 与 P1-06 并行 | Core/provider restart、timer、retry | operation history 与 domain state 对账 |
| P1-06 Node | Node identity、SQLite journal、local inbox/outbox、process controller | Node daemon、journal schema、reconcile loop | P1-03/P1-04 | 与 P1-07 并行 | spawn ACK 丢失、Node restart、PID reuse | journal reconcile 报告 |
| P1-07 Driver SDK | 统一 spawn/attach/invoke/resume/cancel/terminate/inspect | Driver contract、error normalization | P1-03 | 与 P1-06 并行 | fake provider conformance | Provider-neutral Driver tests |
| P1-08 Codex Driver | Codex App Server binding | real Driver、session binding、event mapping | P1-07 | 与 P1-09 并行 | session resume、Harness crash、structured receipt | 固定版本 real conformance |
| P1-09 Second Driver | Claude Agent SDK binding | second real Driver；若无法满足授权/条款，进入明确 blocked gate | P1-07 | 与 P1-08 并行 | same task through two Drivers | 两个异构 Driver conformance |
| P1-10 Surfaces | MCP、CLI、HTTP 调用同一 Core | command/query handlers、CLI smoke | P1-02/P1-03/P1-04 | 与 P1-08/P1-09 并行 | surface parity、permission denial | 同一命令跨三种 Surface 得到一致状态 |
| P1-11 Evidence/Effect | SourceBaseline、Artifact digest、fake Effect Gateway、Finalizer | receipt、evidence、read-back pipeline | P1-04/P1-06 | 与 P1-10 并行 | uncertain effect、partial upload、stale baseline | integrated acceptance evidence |
| P1-12 Local recovery campaign | P1 场景集合执行和问题修复 | reproducible evidence bundle | P1-02 至 P1-11 | 仅在主链路完成后 | E2E-02/03/05/06/07/08/09/12/13/18/19/20/21/25/26/28/33 | P1 Gate Record |

P1 必须证明：

```text
UI/MCP client 退出
→ 已提交 operation 继续由 Durable Operation Provider 处理；外部 Agent Session 按其自身生命周期继续或等待重新绑定

Core 重启
→ Task、Outbox 和已提交 operation 可查询并恢复

Node 重启
→ Journal reconcile，不重复执行未授权的外部进程操作

Harness 崩溃
→ 新 Attempt 或安全 resume

Message ACK 丢失
→ 同一 message_id 重发，不重复消费

外部效果响应丢失
→ uncertain → read-back → adopt/retry

集成基线变化
→ stale/retest，不静默接受
```

P1 退出 Gate：

- 两个真实 Driver 完成固定环境 conformance；
- Harness 自带的 Multi-Agent 能力关闭；
- 任务不依赖原 UI Session；
- Task identity、AgentSlot identity 和 Route identity 不变；
- ACK、send、done、succeeded 均不能绕过 Acceptance；
- Core、Node、Durable Operation Provider 进程和外部 Harness 重启后具有可重复恢复证据；
- P1 只声明一个命名的 Local Profile。

P1 通过后可以发布：

```text
Local Alpha / named profile
```

这个 Profile 必须绑定：

```text
OS
Node
Core version
Temporal version
Driver version
Harness version
database version
policy version
```

### P2 — Cross-Machine Runtime

P2 是用户目标的最低技术完成阶段，目标是让不同机器、不同 Harness、不同 Session 的 Agent 通过 Runtime 完成闭环协作。

P2 工作流：

| Workstream | 交付内容 | 主要测试 | Gate |
|---|---|---|---|
| P2-01 Node enrollment | Machine、Node、incarnation、trust、revoke、rotation | forged node、revoked node、boot change | 身份和信任分离 |
| P2-02 Authenticated channel | outbound HTTPS/WS、poll fallback、channel resume | network loss、reconnect、replay | Node channel 可恢复 |
| P2-03 Transport Resolver | directed Binding、DeliveryPlan、provider switching | asymmetric A→B/B→A、provider failure | 动态切换不丢 message identity |
| P2-04 Durable mailbox | inbox/outbox、cursor、replay、dedup | ACK loss、cursor expiry、duplicate packet | 无漏事件、无重复副作用 |
| P2-05 Runtime lifecycle | remote spawn/attach/resume/terminate | machine restart、harness restart、uncertain spawn | 新 Attempt 安全恢复 |
| P2-06 Source/Artifact transfer | baseline、tree/diff、blob、digest、retention | partial upload、stale baseline、wrong artifact | Evidence 与实际内容一致 |
| P2-07 Lease/fencing | worktree、branch、DB、device、GPU、quota | old owner resume、unfenceable resource | 旧 Owner 不能提交受保护效果 |
| P2-08 Human Bridge | incident、packet、recheck、automatic upgrade | all automatic paths blocked then restored | 临时人工桥接、自动回切 |
| P2-09 Cross-machine campaign | two Nodes、two real Harnesses、review/finalization | E2E-01/04/10/11/14/15/16/17/22/34 | P2 Gate Review |

P2 的目标链路（所有智能判断由外部 Agent 提交；系统执行确定性操作）：

```text
External Management Agent 创建 Goal 并提交 WorkItem/Route 命令
→ Core 持久化并校验 WorkItem
→ Endpoint/resource admission 选择获授权的 Machine/Node
→ Node 绑定 AgentSlot
→ Driver 启动不同 Harness
→ Agent A/B 通过 Runtime Inbox 协作
→ 用户关闭管理界面
→ 网络或 Harness 中断
→ Node/Provider process 恢复已提交 operation
→ 外部 Reviewer 独立验证并提交命令
→ 外部 Agent 提交 Integrated baseline / acceptance 命令
→ 系统执行 read-back 并记录结果
→ 用户从新的入口恢复 Project/Route/Task 视图
```

P2 退出 Gate：

- 真实双机、异构 Harness、关闭原生 Multi-Agent 后成功完成闭环；
- 网络分区不形成双重领域权威；
- 旧 Lease Owner 不能提交受保护写入；
- Human Bridge 只在自动路径耗尽后出现；
- 新能力可触发 Probe 并自动回切；
- 晚到人工包按 message identity、deadline 和 revision 去重；
- Source、Artifact、Message、Runtime Control 的权限彼此独立；
- 证据来自实际 source/artifact/effect read-back；
- 所有结果绑定到固定版本和 Policy Profile。

P2 完成时提交正式 Gate Review，供产品所有者审阅：

- 用户看到的 Project/Route/Agent/Machine 体验；
- 自动化程度；
- Human Bridge UX；
- 数据边界；
- 用户退出后的可见状态；
- 机器和 Harness 可替换性；
- 下一阶段 Hosted 产品方向。

### P3 — Hosted Product

P3 解决产品托管、团队使用和商业化问题。

核心交付：

```text
Organization
Membership
Project
OIDC
Machine enrollment
RBAC / relation policy
tenant-scoped storage
Web Console
usage ledger
budget reservation
quota
audit
notification
backup/restore
retention/export/delete
region/data residency
encryption/key lifecycle
billing integration
SLA/SLO
```

P3 主要工作流：

| Workstream | 目标 | 验收 |
|---|---|---|
| P3-01 Identity/Tenant | 用户、组织、成员、机器和服务身份 | tenant scope、撤销、rotation |
| P3-02 Authorization | 角色、资源、操作、审批和策略版本 | forged tenant、revocation、least privilege |
| P3-03 Console | Project-centric durable state 展示 | 用户无需依赖原始 Session 恢复状态 |
| P3-04 Usage/Budget | Token、compute、provider cost、预算预留 | duplicate webhook、unknown usage、quota |
| P3-05 DR/Governance | backup、restore、retention、export、delete | database、workflow history、blob、key 联合恢复 |
| P3-06 Hosted profile | Managed Cloud / Hybrid / Enterprise self-hosted | 数据驻留、E2EE、source disclosure、SLO |

P3 不改变 Core 的长期身份和任务语义。它只增加托管、治理、商业和用户界面能力。

### P4 — Ecosystem / Scale

P4 解决生态扩展和规模化。

核心交付：

- A2A Gateway；
- 通用 ACP Driver；
- Driver SDK；
- Provider Conformance Certification；
- 更多 Harness；
- 企业 Workspace Provider；
- Schema Registry；
- Generated SDK；
- Version Negotiation；
- Compatibility Window；
- Rolling Upgrade；
- Worker Drain；
- Long-task Migration；
- Sharding；
- Fan-out Control；
- Backpressure；
- Tenant Fairness；
- 大规模 Observability。

P4 验收：

- 新旧 Node/Driver/Protocol 可协商；
- 未识别的安全关键扩展被拒绝；
- Rolling Upgrade 不改变 Root/Route/Task identity；
- 长任务保留旧 Policy 或经过显式迁移；
- 不兼容的 provider process 可以排空；
- A2A Task 不取代内部 WorkItem；
- ACP 不强迫原生 Driver 退化到最低公分母；
- Fan-out、预算、并发、速率和租户公平性有明确上限；
- Provider 故障被局部隔离；
- 每个新 Harness、OS、版本和拓扑都有独立证据。

## 6. Agent 执行模型

### 6.1 本机外部 Management Agent（Codex Harness）

本机 Codex 中运行的外部 Management Agent 负责：

- 长期目标；
- Project/Root/Route 视图；
- Implementation Master Plan；
- Task 拆分并提交具体 WorkItem 命令；
- 依赖和阶段推进；
- 技术决策；
- 向远程外部 Agent 提交执行、消息和绑定命令；
- 证据审查；
- Gate 维护；
- 冲突解决；
- 结果汇总；
- 必要时向用户升级产品、权限或资源问题。

本机外部 Management Agent 主要读取：

```text
GitHub 状态
远程 Codex 状态
远程测试证据
远程 Artifact manifest
远程 SourceBaseline
阶段 Gate Record
```

本机外部 Management Agent 不承担主要工程写入；这是当前研发拓扑中的外部角色分工，不是 Core 内部 Agent 组件。

### 6.2 远程 1302-1 Engineering Codex

远程 Codex 中运行的外部 Engineering Agent 负责：

- `/home/changgeng/Agent-collaboration` 工程实现；
- Runtime package；
- 数据库、Temporal、Node、Driver 和 Surface 开发；
- 测试和故障注入；
- 远程仓库检查；
- 依赖与许可证验证；
- 运行时实验；
- 真实 Harness conformance；
- 证据包生成；
- Git 分支、提交和 Push。

远程 Agent 获得的范围：

```text
Agent-collaboration repository
runtime/ implementation scope
development dependencies
local development services
disposable test fixtures
authorized local credentials
authorized SSH transfer
```

远程 Agent 不自动获得：

```text
unrelated repositories
production credentials
production deployment access
unbounded machine administration
source upload permission
unapproved paid services
```

### 6.3 Future Reviewer / Specialist Agents

未来可由外部 Harness 增加：

- Independent Reviewer；
- Security Specialist；
- Runtime Recovery Specialist；
- Harness Driver Specialist；
- Data/Artifact Specialist；
- Operations/DR Specialist；
- Product UX Reviewer。

这些 Agent 使用独立的：

```text
AgentSlot
Runtime
Grant
WorkItem
SourceBaseline
Context Policy
Evidence Contract
```

Reviewer 默认使用 fresh context，只接收外部 Agent 提交的 sanitized task specification、baseline、evidence 和 acceptance criteria；系统不自动生成 Reviewer 或 Review 策略。

### 6.4 Agent 间协作

当前在 Runtime 尚未自举完成前，采用：

```text
Local Management Codex
        ↓
Remote Engineering Codex
```

正式交付通过：

```text
GitHub branch / commit / push
```

临时日志和一次性 fixture 可以通过：

```text
SSH
```

传输。

每次远程交付必须返回：

```yaml
repository:
  branch:
  base_commit:
  head_commit:
  working_tree:
  push:
  receiver_sync:

task:
  work_item_id:
  attempt_id:
  status:

evidence:
  tests:
  failure_injection:
  source_baseline:
  artifact_manifest:
  external_effects:
  unresolved_items:
```

本机接收后必须读取并核对实际 Git、Artifact、测试和源状态，不能只依据远程 Agent 自述。

## 7. Environment Plan

### 7.1 本机 Windows

用途：

```text
User interaction
Management Agent
Plan management
Remote task dispatch
Evidence review
Gate review
GitHub monitoring
Lightweight coordination state
```

本机不作为 P1 的主要源码开发环境。

本机可以在 P2 作为第二个受控 Node，但前提是：

- 明确授权；
- 机器身份完成 enrollment；
- 本地权限和数据政策明确；
- 不与 Management UI 隐式共享执行权限；
- 使用隔离工作区；
- 通过 GitHub 或受控 Artifact 交换正式事实。

### 7.2 远程 1302-1

用途：

```text
Primary implementation
Primary tests
Runtime experiments
Temporal/PostgreSQL
Machine Node
Harness Drivers
Failure injection
P1 local durable profile
```

P1 预期路径：

```text
/home/changgeng/Agent-collaboration
```

P1-00 必须先核对：

```text
机器可达
项目目录存在
Git remote 正确
分支和 HEAD 可读
工作树状态可读
Node/Codex 能执行
Node/npm/pnpm 版本
PostgreSQL
Temporal
Harness Driver dependencies
```

### 7.3 GitHub

GitHub 是正式事实和版本历史的权威：

```text
source code
schema
migration
tests
formal docs
ADR
Canonical revision
release artifacts
Gate records
```

每个正式阶段使用独立分支：

```text
runtime/p0-contracts
runtime/p1-local-durable
runtime/p2-cross-machine
runtime/p3-hosted
runtime/p4-scale
```

每一阶段的合并前提：

```text
base commit fixed
working tree understood
tests recorded
evidence manifest recorded
review completed
push status explicit
receiver sync explicit
```

### 7.4 SSH

SSH 用于：

- 临时日志；
- 大型一次性 fixture；
- 调试输出；
- 远程只读检查；
- 非 canonical 中间产物；
- 受控 Artifact bundle。

正式源码和正式文档仍以 GitHub 为权威。

### 7.5 PostgreSQL

PostgreSQL 保存：

```text
Root projection
Route projection
AgentSlot
WorkItem
ExecutionAttempt
Task revision
Lease
Grant
Approval
Message
Inbox
Outbox
AcceptedState
Evidence reference
Audit
Usage ledger
```

所有关键领域写入使用：

```text
expected_revision
grant validation
state transition
event append
outbox append
dedup record
```

### 7.6 Durable Execution

P1 采用 Temporal 作为首个参考 Durable Operation Provider，负责已经提交操作的：

```text
long waits
timers
retry
submitted-operation coordination
provider-process reassignment
workflow history
resume
```

Temporal Workflow/Operation ID 映射到：

```text
RuntimeExecutionId
```

而不是：

```text
Project ID
Route ID
WorkItem ID
Harness Session ID
```

WorkItem、AcceptedState 和 Evidence 仍由 PostgreSQL 领域模型拥有。

### 7.7 Machine Node

Node 负责：

```text
Machine identity
Node identity
boot/incarnation
heartbeat
capability probe
local journal
inbox consumer
outbox dispatcher
external-process lifecycle controller
Driver invocation
reconciliation
```

Node 不成为同一领域对象的第二主库。

### 7.8 Harness Drivers

P1 首批 Driver：

```text
Codex App Server Driver
Claude Agent SDK Driver
Deterministic Fake Driver
```

如果第二个真实 Harness 因环境、授权或商业条款无法进入 P1：

```text
P1 真实异构 Driver Gate = blocked
```

替代 Driver 需要记录：

```text
replacement rationale
protocol compatibility
license
version
capability delta
new evidence plan
```

不能静默替换。

## 8. 自举式 Dogfooding Plan

### Stage A — 当前远程控制基线

```text
Local Management Codex
        ↓
Remote Codex / SSH / GitHub
        ↓
/home/changgeng/Agent-collaboration
```

特点：

- 本机管理目标；
- 远程执行工程；
- GitHub 管正式源码；
- SSH 管临时数据；
- 当前文件协议和远程控制保持可恢复；
- Runtime 尚未承担正式任务权威。

退出条件：

- 远程项目路径和 Git 状态可读；
- 远程工程任务可以通过 Git/SSH 交付；
- 当前协作链路有明确回滚方式。

### Stage B — Core 接收外部 Agent 提交的 durable Task

新增 Collaboration Core、领域数据库和 Task API，但实际代码执行仍可通过现有远程 Codex 控制链路完成。

```text
External Management Agent
        ↓ explicit task command
Core persists durable WorkItem
        ↓
Existing remote control executes
        ↓
Evidence returns to Core
```

退出条件：

- Task 和 Attempt 有稳定 ID；
- Core 重启后 Task 可恢复；
- 现有远程控制仍可作为 fallback；
- 新 Core 不改变旧 Root/Route 身份。

### Stage C — Remote Codex 成为 Managed Runtime Driver

把远程 Codex 绑定为：

```text
AgentSlot
→ AgentRuntime
→ Machine Node
→ Codex Driver
→ Harness Session
```

此时远程 Agent 仍可以使用现有连接机制作为恢复路径，但正常调用通过 Driver Contract 进入。

退出条件：

- AgentSlot 与 Harness Session 解耦；
- Driver 可返回结构化 start/turn/error/receipt；
- Session 替换不改变 WorkItem 和 Route；
- Node 能完成基本 journal reconcile。

### Stage D — 消息迁移到 Packet / Inbox / Receipt

把本机到远程的工程消息从手工叙述迁移为：

```text
Collaboration Packet
→ authenticated transport
→ Node inbox
→ Driver invoke
→ structured receipt
```

用户 Relay 仍保留为 Human Bridge recovery incident，但不再作为正常开发路径。

退出条件：

- message identity 稳定；
- inbox 去重；
- ACK 丢失可恢复；
- response 可以回传；
- Git source sync 和 Message Transport 仍独立；
- 旧手工链路仍能在故障时恢复。

### Stage E — 外部 Agent 通过 Runtime 持续推进工程任务

外部 Management/Route/Engineer Agent 通过 Collaboration System 提交并持续推进：

```text
external command creates or revises WorkItem
→ authorized operation is admitted
→ external Agent invokes remote Driver
→ submitted operation can wait/resume
→ external Reviewer evaluates evidence
→ external Agent submits finalization/acceptance command
```

Durable Operation Provider 只处理上述已提交 operation 的等待、重试、投递、绑定和恢复；它不生成 Agent 的推理步骤、团队关系或验收判断。旧远程控制机制仍保留为受控恢复入口。

退出条件：

- P1 本地 durable 和 P2 跨机能力达到对应 Gate；
- Runtime 不依赖某个用户 UI Session；
- 失败时能通过旧控制链路恢复；
- 所有核心状态可导出。

### Stage F — Project Dogfooding

项目自身的开发流程完整使用：

```text
User
→ External Management Agent
→ External Route Agent
→ External Engineer / Reviewer Agent

横向由 Collaboration System 提供：
AgentSlot / Scope
→ Runtime Driver
→ Node
→ Durable Operation Provider
→ Evidence / AcceptedState command
```

此时 `agent-collaboration` 由外部 Agent hierarchy 通过自身的 Collaboration System 管理跨 Harness 工程协作；系统继续只执行已提交的确定性操作。

## 9. P1 的首批执行任务顺序

P0 已在本计划中完成决策冻结。获得执行授权后，远程 Engineering Codex 按以下顺序直接推进。

| 顺序 | Work Item | 目标 | 主要依赖 | 验收 |
|---:|---|---|---|---|
| P1-00 | Remote Environment Baseline | 验证 1302-1、项目、Git、Node、数据库、Temporal、Driver 环境 | P0 Authorization | 环境清单、版本和权限记录 |
| P1-01 | Runtime Workspace Scaffold | 建立独立 Runtime package 和 CI | P1-00 | install/typecheck/test 启动 |
| P1-02 | Scope and Domain Core | 实现 Scope/ScopeBinding、Root/Route/AgentSlot/WorkItem/Attempt/Lease/AcceptedState | P0 contracts | domain unit tests |
| P1-03 | Protocol v0 | 固化 Command、Packet、Receipt、Capability schema | P1-02 | schema positive/negative fixtures |
| P1-04 | PostgreSQL Authority | 实现事务、CAS、events、inbox/outbox、dedup | P1-02/P1-03 | crash-after-commit、duplicate command |
| P1-05 | Durable Operation Adapter | 接入 Workflow/Activity、timer、retry、wait、reconcile | P1-04 | Core/provider-process restart |
| P1-06 | Machine Node | 实现 Node identity、journal、consumer、external-process lifecycle controller | P1-03/P1-04 | spawn ACK loss、Node restart |
| P1-07 | Driver Contract | 实现统一 Driver 接口和错误映射 | P1-03 | fake driver conformance |
| P1-08 | Codex Driver | 接入 Codex App Server | P1-07 | start/resume/invoke/receipt |
| P1-09 | Second Real Driver | 接入 Claude SDK 或经 ADR 批准的替代 Driver | P1-07 | 异构 Driver 一致任务 |
| P1-10 | Surface Parity | MCP、CLI、HTTP 共用 Core | P1-02/P1-04 | 同命令、同状态、同权限结果 |
| P1-11 | Evidence/Effect | SourceBaseline、Artifact、fake Effect Gateway、Finalizer | P1-04/P1-06 | stale、partial、uncertain/read-back |
| P1-12 | Recovery Campaign | 执行 P1 场景并修复问题 | P1-02 至 P1-11 | P1 Gate Record |

P1-00 是唯一需要先确认远程项目当前状态的任务。它不会改变架构，只会锁定执行事实。

## 10. 用户干预和升级规则

### 日常默认模式

以下工作由本机外部 Management Agent 和远程外部 Engineering Agent 自行完成：

- 技术决策；
- 依赖选择；
- Task 拆分并提交具体 WorkItem 命令；
- 代码实现；
- 测试；
- 调试；
- 失败恢复；
- 文档更新；
- Git 分支与提交；
- 证据整理；
- 阶段内 Review；
- 下一 WorkItem 的判断和命令提交。

用户不参与每个小任务、每个依赖或每个技术实现选择。

### 需要提前升级给用户的情况

只有以下情况需要中断：

1. 新的破坏性操作；
2. 新的生产环境变更；
3. 新的凭据访问；
4. 新的账号或付费资源；
5. 新的源码或聊天数据外传；
6. 必须增加机器或设备；
7. 必须改变用户可见产品行为；
8. 真实实验否定已冻结的核心架构；
9. 无法在当前授权范围内恢复；
10. P2 Gate 需要产品方向确认。

升级信息必须包含：

```text
Observed evidence
Impact
Alternatives
Recommendation
Required decision
```

不要只发送“你想怎么做”。

### P2 人工 Gate

P2 完成后提交：

```text
Cross-Machine Gate Review
```

内容包括：

- 双机拓扑；
- Harness/Driver/OS/Protocol 版本；
- AgentSlot/Runtime/Session 绑定；
- 消息投递和消费证据；
- 网络分区恢复；
- Lease/Fencing；
- Human Bridge UX；
- 用户退出后的体验；
- Source/Artifact 数据边界；
- 已知限制；
- 下一阶段产品建议。

P2 是默认主要人工评审节点。

### P2 后的产品确认

进入 P3 前，用户主要确认：

- 默认使用 Local、Hybrid 还是 Hosted；
- Web Console 信息层级；
- 用户是否允许默认后台执行；
- 源码、聊天、Artifact 的托管策略；
- 团队权限和审计范围；
- 计费与预算呈现；
- Hosted 与 Self-hosted 的优先级。

技术实现由执行 Agent 根据本计划继续推进。

## 11. 计划完成标准

本计划达到 Implementation-ready Baseline 的条件：

- 12 项 ADR 已有明确状态；
- Pre-P0 决策准备已收敛；
- Canonical Delta 已冻结；
- P1 Profile 已确定；
- Domain authority 已确定；
- Durable Provider 选择已确定；
- Driver 策略已确定；
- Protocol/API 边界已确定；
- Message/Receipt semantics 已确定；
- Lease/Fencing semantics 已确定；
- Failure/Recovery semantics 已确定；
- Security baseline 已确定；
- Data policy 已确定；
- Migration/rollback 已确定；
- Agent 分工已确定；
- 本机/远程/GitHub/SSH 环境边界已确定；
- Dogfooding Stage A–F 已确定；
- P1 首批 Work Items、依赖、并行关系和 Gate 已确定；
- 用户日常参与保持最小化；
- P2 作为默认主要人工 Gate；
- 真实未验证事项有明确的 P1/P2 验证方法；
- 后续执行 Agent 无需重新选择核心技术架构。

### `not_run` 产品事实政策

关于未运行验收场景的正式产品定义、用户承诺边界、状态词典、P0–P4 验证升级路径、Gate 证据合同和发布文案，统一参见：

[not_run 产品事实与验证边界说明](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-09-not-run-product-facts/not-run-product-facts.zh-CN.md)

该说明是实施计划的产品层配套合同。它要求把 `not_run` 绑定到具体能力、Profile、机器、Harness、版本、方向、授权范围和证据集合；未完成对应 Gate 前，不得将其升级为 `supported`。

后续能力状态沿用：

```text
Proposed
→ Adopted
→ Implemented
→ Verified on pinned environment
→ Supported for named Profile
→ Released
```

任何一项能力只有在既有五层证据齐全后才能称为 `supported`：

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

研究包和当前仓库的最终事实入口：

- [Architecture-RFC-v2.zh-CN.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/Architecture-RFC-v2.zh-CN.md:1)
- [architecture-decisions.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/architecture-decisions.json:1)
- [deliverables.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/deliverables.json:1)
- [state-machines.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/state-machines.json:1)
- [acceptance-scenarios.json](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/acceptance-scenarios.json:1)
- [capability-matrix.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/capability-matrix.md:1)
- [validation-report.md](D:/Chatgpt/Agent-collaboration/RFC_TEMP_SOURCE/2026-09-08-cross-harness-runtime-final/validation-report.md:1)

本计划完成后，实施 Agent 可以从 `P1-00 Remote Environment Baseline` 开始，在远程 `1302-1` 的 `/home/changgeng/Agent-collaboration` 中进入第一段真实 Runtime 工程。

