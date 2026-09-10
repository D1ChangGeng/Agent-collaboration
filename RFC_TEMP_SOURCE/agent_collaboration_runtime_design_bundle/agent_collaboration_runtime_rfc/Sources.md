# 来源索引

研究日期：2026-09-07；架构边界修订确认：2026-09-09。外部资料为官方规范、官方文档、维护者源码、许可证或原始研究。

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

### [S19] LangGraph persistence and checkpoint semantics（外部技术背景；不属于 Collaboration System 核心）

来源类型：`official_documentation`；查阅日期：2026-09-07。该来源仅用于说明外部 Harness Agent 的可选技术，不构成 Collaboration System 的组件或实现依赖。

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
