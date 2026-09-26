# Build / Buy / Integrate / Extend Matrix

状态：Accepted architecture baseline；用于后续实现选择和 Provider conformance，不等于当前产品支持。

| 能力 | 推荐路径 | 我们拥有的边界 | 优先候选 | 主要风险/门槛 | 当前证据 |
|---|---|---|---|---|---|
| Root / Route / WorkItem / accepted state | Build | 长期身份、任务语义、验收和迁移 | 自有 Collaboration Core | 领域膨胀、双写权威 | confirmed-local 的既有 Root/Route；WorkItem 为 accepted architecture contract |
| 领域事务与事件 | Integrate + Compose | schema、不变量、事件版本、outbox | PostgreSQL + append-only domain events | DB 热点、迁移、灾备 | architecture-allowed |
| Durable operations | Integrate | 已提交命令/投递/租约/效果操作的版本、重试、等待和恢复合同 | Temporal 首个参考 Provider | 运维、确定性、引擎历史与领域状态分工 | source-reviewed；not-run |
| Local-first durable profile | Extend/Integrate | Profile、导出、迁移 | DBOS + PostgreSQL/SQLite 评估 | 数据库耦合、跨机能力需补齐 | source-reviewed；benchmark not-run |
| External Agent reasoning and orchestration | Harness-owned / outside boundary | 外部 Agent 自主的 reasoning、planning、delegation、team composition 和 task decomposition；系统只校验命令、绑定、回执和协作状态 | Codex、Claude Code、OpenCode 或其他外部 Harness | 将 Agent 决策误写入基础设施状态机 | source-reviewed as external background |
| Durable operation alternative | Integrate only after review | Provider adapter | Dapr（已有 sidecar/Kubernetes 时） | 平台依赖、至少一次 activity | source-reviewed |
| Durable operation handler alternative | Experimental | 适配边界和许可审查 | Restate | BSL 1.1 与托管服务边界 | source-reviewed；commercial review required |
| Message inbox/outbox | Compose | message identity、去重、receipt | PostgreSQL outbox；高吞吐时 NATS JetStream | broker ACK 不等于执行完成 | source-reviewed；not-run |
| Agent protocol | Build + standard bindings | Collaboration Packet、CommandEnvelope、状态语义 | versioned HTTP/RPC core | schema 演进、兼容 | accepted architecture contract |
| Tool surface | Integrate | service handler、授权映射 | MCP（双代协商，Tasks 可选） | client/server 未同时支持 Tasks | source-reviewed |
| External agent interop | Integrate | 外部 Attempt 映射、信任降级 | A2A Gateway | AgentCard/Task 不等于部署或产品验收 | source-reviewed |
| Coding runtime edge | Integrate/Wrap | Driver contract、错误、恢复映射 | ACP、Codex App Server、Claude SDK、Gemini/Cursor/OpenHands CLI/SDK | 版本与权限差异 | source-reviewed；E2E not-run |
| Machine/node connectivity | Compose/Integrate | enrollment、trust、incarnation、channel | outbound HTTPS/WS；已有 Tailscale/SSH | 联通不等于 addressability 或 execute | source-reviewed |
| Process persistence | Integrate | provider lifecycle 和 checkpoint 映射 | native supervisor、service、container；tmux 兼容 | PTY 存活不等于执行恢复 | architecture-allowed |
| Artifact/blob | Integrate/Wrap | manifest、digest、ACL、retention | S3-compatible/local immutable blob | GC、驻留、完整性与真实性混淆 | source-reviewed |
| Source/cache | Integrate | baseline、可复现性、证据 | Git/SSH；Bazel CAS 仅适用构建 | cache poisoning、非确定性结果 | source-reviewed |
| Authentication | Buy/Integrate | subject 映射、enrollment policy | OIDC/Keycloak | issuer/audience、token 混用 | source-reviewed |
| Authorization | Integrate | 角色、scope、grant、审批 | OPA；复杂关系按需 OpenFGA | 策略版本与撤销 | source-reviewed |
| Secrets/workload identity | Integrate | credential reference、最小权限 | OS keychain/KMS/OpenBao/SPIRE | secret 泄漏到 prompt/packet/sandbox | source-reviewed |
| Observability | Integrate | correlation、证据质量、成本状态 | OpenTelemetry | prompt/source 泄漏、高基数 | source-reviewed |
| Usage/billing | Build ledger + Integrate payment | raw/estimated/reconciled/unknown usage | Stripe Billing 等支付基础设施 | 重复计量、迟到回执 | source-reviewed |
| Human UI | Build product surface | durable state、审批、接管、导出 | Web Console + API client | 把聊天或连接当项目主对象 | future product surface; architecture accepted |

## 选择规则

1. 核心协作语义、Scope/身份、权威状态转换、accepted state、ownership/fencing、evidence 和 finalization records 由我们拥有；外部 Agent 决定团队和工作内容。
2. 通用数据库、工作流、对象存储、身份、策略、遥测和支付能力优先集成成熟实现。
3. 不把任何第三方的 session、thread、run、task 或 event ID 直接暴露成 Project/Root/Route/WorkItem 主键。
4. 许可证、数据驻留、供应商条款和托管边界在锁定版本后重新审核；研究来源中的 `main`、`latest` 和产品文档不是永久版本凭证。
5. 首版只选一个 Durable Operation Provider 进入真实 conformance；其余保持 adapter 级研究，避免同时维护多个恢复语义。Provider 只恢复已提交操作，不生成 Agent reasoning。
