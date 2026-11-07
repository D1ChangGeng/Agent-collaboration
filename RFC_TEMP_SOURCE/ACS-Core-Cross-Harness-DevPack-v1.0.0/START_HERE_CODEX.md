你要在现有 `D1ChangGeng/Agent-collaboration` 上完成 ACS Core 跨 Harness 可靠通信增强，按本开发包交付可运行源码与工程验收证据。不要停留在计划、文档或 mock 演示。此指令是后续 Codex 的执行授权范围；本开发包的生成本身没有修改业务仓库。

## 先做什么

1. 读取项目自身 AGENTS.md、工作树状态和本包 `docs/00_SCOPE_AND_DOD.md`、`01_BASELINE_AND_EVOLUTION.md`、`13_WORK_PACKAGES.md`。使用本包 `tools/capture_baseline.py --acs <repo> --orca <repo> --out <path>` 记录本地版本；该工具只读 Git 元数据。
2. 确认 ACS 参考提交、当前提交、未提交改动、实际运行服务是三种不同事实。不得重置用户工作树。无 Orca checkout 时在独立目录只读获取其公开源码并固定 revision；不能把网络不可用伪装成已核对。
3. 在实际开发过程中定位模块，更新 `handoff/implementation-ledger.json` 的工作副本。WP00 是源码定位和基线检查，不是研究阶段；完成后继续 WP01，不等待新一轮方向确认。
4. 按工作包依赖推进。数据库/授权/Native 输入副作用由一个集成人控制；并行工作仅在独立边界内开展。所有工具发现、调用和事件分发复用相同授权策略。

## 必须交付

实现已有通信主链的增量增强、能力感知 Adapter、可安全恢复的投递运行时、客户端查询/状态/事件/附件服务、无 UI Orca 集成接口与头部无界面消费者、自动化契约/集成/回归测试、兼容迁移与最终证据。实现文件路径可根据真实仓库调整，语义和验收不可降低。

现有 Codex/OpenCode 接收链必须保持可用并完成新契约接入。必须提供 Orca-owned receiver 适配接口与非模拟的协议层接入代码；公开插件 API 不足的能力用显式 `unsupported` 和已定位的宿主扩展接口表达，不得通过假 ACK 或直接修改 Orca SQLite 冒充支持。完整 UI readiness 以 `docs/10_ORCA_UI_READINESS.md` 的分层标准判定，不能以一项 `send` 接口或 SDK 类型检查代替。

## 不可改变的语义

- Client 来自受信绑定，不来自未绑定 Session。Root/Route/AgentSlot 组织保留。项目管理权限不自动赋予读取全部私信的权限。
- 普通消息不需要 Task/Run/Dispatch/Gate。`send_message` 仍为自然发信、提问、纠正、回复和交接的统一动作。
- 回复必须由真实对端主动提交 `reply_to`。Native 完成、工具结果、UI 读取、Provider consumed、系统通知都不能生成 Agent 回复。
- 未知状态是事实，不是错误装饰。发生潜在 Native 副作用后不能因为超时、重启或换 Session 就重新输入。
- `activation=message_only` 永不产生该消息的自动 Native 激活；`sync` 只是等待模式。超时只结束观察。
- Core 不接管原生 transcript、工具执行、Task 结算、工作区、审批决策和代码质量。必要运行状态只用于通信准入/诊断；完整执行视图由 Orca/Harness 提供。

## 明确排除

不组织 ACS/Orca 比较实验、研究性 PoC、新产品视觉研究、完整 UI 移植、独立客户端开发。不要重建已有组织模型，也不要为“通用性”重新引入 WorkItem。工程所必需的静态阅读、真实协议集成、故障注入回归、契约测试和验收必须做。

## 实施自主权

你可自主选择具体 SQL 列、模块拆分、分页查询、索引和内部并发策略；每次偏离本包建议实现记录理由和测试。不可降低身份、权限、回执证据、未知状态和兼容语义。机器契约新增字段要同步 Schema、OpenAPI、SDK、夹具与测试。若实际 API 版本不同，先做兼容适配；禁止按名称猜能力。

## 运行与发布边界

仅在隔离开发/测试命名空间和获授权的 Harness/主机运行测试；不使用生产私信作为夹具，不向用户现有联系人发测试消息。使用真实模型是工程端到端验证，不是比较实验。缺少凭据或接收环境时继续其他可做工作，输出明确阻塞项，相关资格不得写通过。

默认仅本地代码、测试与文档交付；不自动合并、打 Tag、发布、生产迁移、切换远端 Runtime 或发送上游 PR。修改生产和公开发布需要单独授权。

## 收尾

按 `handoff/FINAL_REPORT_TEMPLATE.md` 输出实际提交/工作树清单、测试命令和原始日志、迁移/回滚演练、旧客户端回归、能力资格矩阵、UI feature 逐项映射、宿主缺口及真实未完成项。所有 WP 和 R 条目闭环；实现未完成时明确标记，不以 fixture 通过冒充产品完成。
