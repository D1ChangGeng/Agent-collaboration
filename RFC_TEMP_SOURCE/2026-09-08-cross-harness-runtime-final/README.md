# Cross-Harness Runtime Architecture Research Package

状态：Accepted architecture baseline / implementation-not-started

研究日期：2026-09-08（Asia/Shanghai）

本目录是基于用户提供的两份设计基线、升级设计输入、现有 `Agent-collaboration` 仓库和公开一手资料形成的独立研究包。架构边界已经冻结为：User → 外部 Management Agent → 外部 Route Agent → 外部 Engineer/Reviewer/Finalizer Agent；Agent Collaboration System 是横向基础设施，不属于该层级。它用于后续实现规划；不表示本目录中的 Runtime、Control Plane、Node、Driver 或故障恢复能力已经在产品中存在。

## 文件导航

| 文件 | 用途 | 当前状态 |
|---|---|---|
| `Architecture-RFC-v2.zh-CN.md` | 总体架构、边界、决策、迁移和端到端场景 | Accepted baseline |
| `architecture-decisions.json` | 12 项已收敛 ADR | accepted_architecture_baseline |
| `deliverables.json` | 用户要求的 12 项交付物到章节/文件映射 | accepted_architecture_delivery_map |
| `state-machines.json` | WorkItem、Attempt、Runtime、Handoff、Lease、Machine、Session、Effect 状态合同 | accepted contract; implementation pending |
| `collaboration-packet.schema.json` | 协作包结构草案 | draft schema |
| `command.schema.json` | 统一命令外壳草案 | draft schema |
| `capability-observation.schema.json` | 有范围和有效期的三态能力观察草案 | draft schema |
| `acceptance-scenarios.json` | 34 个实施/故障注入验收场景 | 全部 not_run |
| `sources-2026-09-07-snapshot.json` | 2026-09-07 研究来源索引 | snapshot |
| `evidence-ledger-2026-09-08.json` | 本轮输入、版本、仓库和外部页面校验账本 | current snapshot |
| `build-buy-integrate-extend-matrix.md` | 能力选型和复用决策矩阵 | Accepted baseline |
| `capability-matrix.md` | Harness/协议/部署能力证据矩阵 | 未完成 E2E |
| `validation-report.md` | 本轮结构与仓库验证结果 | current snapshot |
| `not-run-product-facts.zh-CN.md` | `not_run` 的产品事实、用户承诺边界、状态词典、P0–P4 Gate 与发布规则 | accepted product-policy clarification |
| `agent-boundary-contract.json` | 外部 Agent 与横向基础设施职责边界 | accepted contract |
| `scope-model.schema.json` | Root/Route/Engineer Source Scope 与 ScopeBinding 合同 | accepted schema |
| `boundary-validation-results.json` | 外部 Agent 边界与 Scope 合同校验结果 | PASS |
| `validate_boundary_surfaces.py` | 边界残留与 Scope schema 的可重复校验 | PASS；不证明运行时 |
| `validate_schema_fixtures.py` 与 `example-*.json` | schema 正例/反例的可重复结构校验 | PASS；不证明运行时 |
| `manifest.json` | 除 manifest 自身外的最终文件摘要 | current snapshot |

## 证据等级

- `confirmed-local`：本地仓库源码、测试或当前文件直接确认。
- `source-reviewed`：公开规范、官方文档或维护者源码已读取；只证明该资料描述或表达了能力。
- `architecture-allowed`：现有模型允许该方向，但没有产品机制。
- `unverified`：实现或部署可能存在，但本轮没有足够验证。
- `not-run`：验收场景已定义，尚未执行。
- `unknown`：当前范围内没有足够事实。

产品 `supported` 仍需满足既有五层合同：说明、决策逻辑、真实机制、不变量验证和代表性端到端证据。

`not_run` 的产品含义和用户可见边界见 [`not-run-product-facts.zh-CN.md`](not-run-product-facts.zh-CN.md)。

## 使用顺序

1. 先阅读 RFC 的结论、Canonical delta、组件边界和决策门。
2. 按已冻结的 `architecture-decisions.json` 与 `state-machines.json` 作为实施合同输入；实施阶段只在真实证据否定合同或需要产品政策变化时开启复议。
3. 用 `evidence-ledger-2026-09-08.json` 和两个矩阵锁定版本、范围、证据等级和未知项。
4. P0 合同已冻结；P1 实现仍须通过环境、版本、授权和回滚 Gate。不得因 RFC 文件存在而自动启动外部 Agent、上传源代码或改变现有项目权限。
5. 每个 Harness、机器、Provider、协议版本和部署 Profile 都必须单独获得 conformance 与 E2E 证据。

## 保留边界

现有 `Agent-collaboration` 仓库仍是 setup-only Skill + repository/Workspace/Route 文件协议。Root/Route/Scope identity、`AGENTS.md`、`.agents/knowledge/`、项目-owned 文件和非破坏迁移边界必须保留；本研究包不替换它们，也不把未来 Runtime 状态写入现有 setup manifest 或 Root registry。外部 Agent 负责 reasoning、planning、delegation、team composition 和 task decomposition；系统负责身份、寻址、消息、绑定、资源、证据和恢复。
