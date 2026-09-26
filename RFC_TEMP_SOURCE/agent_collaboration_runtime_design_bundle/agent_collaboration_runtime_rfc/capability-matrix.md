# Harness / Protocol / Deployment Capability Matrix

状态：候选能力与证据索引；不是 `supported` 清单。外部 Agent 的 reasoning、planning、delegation 和 team composition 由 Harness 自有 Runtime 承担；本系统只验证绑定、通信和恢复。

## 证据规则

`D` = 文档/规范表达或源码存在候选路径；`L` = 本地 `Agent-collaboration` 源码/测试确认；`U` = 本轮未在目标部署实例验证；`N` = 尚未实现或未运行。只有五层证据齐全才可标记产品 `supported`。

| Surface / Provider | discovery | spawn/attach | send/consume | resume | structured receipt | 跨机 E2E | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| ACHP 文件协议 | L | N | user manual only | session-owned | handoff template | N | setup/runtime contract；不是执行引擎 |
| MCP base 2026-07-28 | D | N | tool call only | session-independent task mapping | structured tool result | U | 工具 Surface；后台 Agent 执行需另一个获授权的 headless 外部 Harness Agent |
| MCP Tasks extension | D | N | task handle/poll/update/cancel | handle可重连 | task result/error | U | 双方显式支持才可用 |
| A2A 1.0.0 page observed 2026-09-08 | AgentCard D | external service dependent | Send/stream/push D | Get/Subscribe D | Task/Artifact D | U | 外部 Agent gateway；不等同产品 Task |
| ACP v1 | D | session/new D | session/prompt D | session/load if capability | update/stop reason D | U | Runtime Driver edge |
| Codex App Server | D | D | D | thread resume candidate | turn/item events D | U | 首批 Driver 候选，未做本项目 E2E |
| Claude Agent SDK | D | D | D | session resume candidate | SDK events D | U | 首批 Driver 候选，授权/条款需复核 |
| Gemini CLI | D | headless D | CLI output D | session resume D | JSON/stream candidate | U | Driver candidate |
| Cursor CLI | D | headless D | structured output D | resume D | JSON/stream candidate | U | Driver candidate |
| OpenHands Agent Server/SDK | D | server dependent | API/events D | conversation persistence D | event/API D | U | Provider candidate |
| Temporal | D | provider worker process D | task queue D | event history/replay D | history/visibility D | U | Durable Operation Provider candidate；只处理已提交操作 |
| DBOS | D | app/runtime dependent | durable queue D | checkpoint D | DB-backed state D | U | local/Postgres profile candidate |
| Node outbound channel | N | N | N | N | N | N | future infrastructure implementation |
| Machine enrollment/trust | N | N | N | N | N | N | future implementation |
| Human Bridge | L semantic envelope | N | user transport | packet identity | manual receipt contract | N | recovery incident only after policy gate |

## 当前本地事实

- 仓库当前是 setup-only Skill 与文件协议；没有 daemon、MCP Server、HTTP/RPC/A2A 服务、数据库事件存储、任务队列、调度器、租约管理器、机器池、Artifact Store 或 Web Console。
- 现有自动 relay policy 只允许在 exact send capability、目标可寻址和交付可观察性被验证时使用；仓库没有 runtime probe/send 实现。
- 当前 topology 仅记录本地会话；跨会话、跨主机、双向交付、断线恢复均为 `unknown` / `unverified`。
- 本矩阵不证明系统能够自行创建 Agent、决定团队结构、拆分任务或继续外部 Agent reasoning；外部 Session 消失且无可用绑定时，系统保存 pending/blocked 状态并等待重新绑定。
