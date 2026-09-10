# Validation Report

研究包状态：Accepted architecture baseline / implementation-not-started

## 本轮已执行

| 检查 | 结果 | 说明 |
|---|---|---|
| 现有仓库单元测试 | PASS | 67 tests passed；覆盖 setup、Workspace/Route、schema、保留和幂等行为 |
| `scripts/validate_skill.py` | PASS | 现有 Skill 结构校验通过 |
| `scripts/project_setup.py validate --root .` | PASS | 当前仓库 ACHP 0.3.0 setup 结构有效 |
| `git diff --check` | PASS | 检查时无新增空白错误 |
| 公开 MCP 2026-07-28 页面抓取 | PASS | HTTP 200；页面快照哈希记录在 evidence ledger |
| MCP Tasks 页面抓取 | PASS | HTTP 200；页面快照哈希记录在 evidence ledger |
| A2A latest 页面抓取 | PASS | HTTP 200；观察到 v1.0.0 文本及任务/产物/推送目录 |
| Temporal 架构页面抓取 | PASS | HTTP 200；观察到 Client/Server/Worker、Event History、Task Queue |
| LangGraph durable execution 页面抓取 | PASS | HTTP 200；作为外部 Agent 技术背景保留，不属于 Collaboration System 核心或实现依赖 |
| External Agent boundary static review | PASS | Root/Route/Engineer hierarchy is external to the Collaboration System; no internal Management Agent, Planner, Supervisor Agent, Agent Graph or LangGraph implementation dependency remains |
| Scope boundary review | PASS | Root/Route/Engineer Source Scope and external AgentSlot/Session binding semantics are present in the RFC and accepted contracts |
| Boundary contract validator | PASS | `validate_boundary_surfaces.py` passed external-Agent boundary, forbidden-residue and Scope schema checks |
| ACP v1 overview 抓取 | PASS | HTTP 200；观察到 session/new/prompt/load/cancel/update |
| 研究包 JSON 结构检查 | PASS | 17 个 JSON 文件均可解析；最终 manifest 已按 25 个非 manifest 文件重算并完成字节数/SHA-256 核对 |
| 研究包 manifest 完整性 | PASS | manifest 自身未纳入摘要；25 个条目与实际文件逐项匹配 |
| Schema/fixture 校验 | PASS | 3 组 schema/正例与 7 个反例通过；该检查不证明真实运行时 |
| 12 项交付物映射检查 | PASS | `deliverables.json` 覆盖 D-01 至 D-12，并指向正文/配套产物 |
| 真实双机/异构 Harness E2E | NOT RUN | 不把设计文件当运行证据 |
| 崩溃、网络分区、租约 fencing、外部效果不确定性 | NOT RUN | 见 `acceptance-scenarios.json` |

## 当前仓库基线

本地仓库在最终验证时的提交为 `2b992a49b1349de0902443de215ee3bf2b975679`，分支为 `codex/v04-user-journey`。研究期间分支和 tracked-file 状态曾发生外部变化；最终状态中 `README.md`、`README.zh-CN.md`、`SKILL.md` 及三个 `references/` 文件存在本研究包之外的修改或新增。本轮正式产出包括 final package、bundle 镜像、顶层 RFC 兼容镜像和独立的 `not_run` 产品事实说明目录；没有覆盖、采用或验证这些外部变化。研究包未修改现有 `AGENTS.md`、Skill 运行机制、数据库、凭据或远程系统。

## 不能从这些检查推出的结论

- 不能推出任何 Harness 已具备跨机器 send、wake、spawn、resume 或 delivery receipt。
- 不能推出 MCP Tasks 已被所有客户端和服务器支持。
- 不能推出 A2A AgentCard 是实际部署、权限或租户授权证明。
- 不能推出 Temporal、DBOS 或其他 Durable Operation Provider 已经接入本项目；LangGraph 页面仅是外部 Agent 技术背景，不构成本系统实现依赖。
- 不能推出用户退出 UI 后已有任务会继续执行。
- 不能推出 Human Bridge 已经可以自动升级回系统管理 Transport。
- 不能推出外部副作用具备 exactly-once 语义。

## P1 实施前置门

P0 合同已在本研究包中冻结；进入 P1 实施前仍必须完成：

1. External Agent boundary、Scope/ScopeBinding 与 Durable Operation Provider boundary 已冻结；实现时固定对应版本。
2. 固定 Domain schema、authority、outbox、lease/fencing 和 security threat model 的实现版本。
3. 固定首个 Durable Operation Provider、Node/Driver 版本、许可证和数据驻留策略。
4. 定义可重复的 conformance harness 和故障注入环境。
5. 明确批准范围、回滚方式、源代码/聊天/凭据的数据边界。
