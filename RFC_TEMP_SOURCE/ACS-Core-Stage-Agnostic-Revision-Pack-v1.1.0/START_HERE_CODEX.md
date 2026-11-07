# Codex 执行入口｜ACS Core 阶段无关修订 v1.1.0

你现在正在开发（或即将开发）`D1ChangGeng/Agent-collaboration` 的跨 Harness 可靠通信能力。**此前 v1.0.0 开发包视为已经交付过，但当前进度完全未知；不得假定任何 WP 未开始、已结束或可重做。** 请在当前实际代码基础上直接接续工作，不向用户追问旧包进度，不复位仓库，不覆盖现存成果。

## 一、立即应用的新决策

1. 本包修订既有范围：**P0 = 受信自然通信及 Harness 原生接收正确性/覆盖；P1 = 面向 Orca 集成的最小完整 ACS 通信服务与数据契约；P2 = 附件、跨设备草稿、个人阅读/静音/归档、全文搜索等扩展，不作为当前 P0/P1 完成门槛。**
2. 当前 ACS 的 `send_message`、AgentSlot/可信 Client、Project/Root/Route、`reply_to`、Inbox/Outbox、Native ACK 分层、`message_only`、等待恢复均为保留契约。**不要为了参考 Orca 重建 ACS Core 或重新引入 Task/Run/Dispatch/Gate 业务状态。**
3. **P0 先于依赖它的 P1 变化，但不要求按旧 WP 数字顺序重做。** 修改/测试对象以现有能力缺口为准；旧代码已符合新契约则标 `retained_verified` 并链接证据，不创建无意义 commit。
4. `contracts/` 中旧 R/T/UI/API 的完整映射是本版范围的机器权威。原包的 96 个 T 全标 P0、附件/草稿全列必交等设定被此版覆盖。原包 API/Schema 可用于 P1/P2 实现参考，不得据其字段存在就强制交付 P2。
5. 不能为了缩小范围放弃 Core 正确性、已存在的用户功能、回归、迁移或安全边界；已实现的 P2 **不删除、不回滚**，若受正在进行的安全修复影响则保障不回归。

## 二、无论现阶段如何，使用同一接续过程

- 读取**实际**目标仓库 `AGENTS.md`、Git 状态、当前提交与未提交改动；读取本版 `docs/00_GOVERNANCE.md`、`docs/01_ANY_STAGE_EXECUTION.md`、`docs/02_CHANGE_SURFACES.md`、`docs/03_P0_HARNESS_RUNTIME.md`、`docs/04_P1_CLIENT_SURFACES.md`、`docs/06_CORRECTNESS_AND_SECURITY.md`。
- 运行 `python tools/capture_state.py --acs <ACS源码目录> --out <报告文件>`，它只读 git/路径并输出**观察线索**，绝不自动判定已完成或通过；若未有 Python 可手动记录相同字段。
- 对照本包 `contracts/change-items.json` 和实际源码/测试/证据，逐项分类：`retained_verified / implemented_needs_evidence / partial / absent / incompatible / blocked`。只有实际证据可成为 `retained_verified`。
- 以**缺口驱动**的任务计划实施，保持已合并和进行中的正确工作。发现正在开发 P2：完成必要的安全/数据一致性收尾或隔离为后续工作，不主动销毁成果；不继续扩张新的 P2 范围。
- 对现有代码的修订采用最小兼容差异。提交每个改动前检查是否复用现有 Authority、operation、Outbox、Node Journal、Receiver；禁止另建同义账本、双输入 owner 或双消息权威。
- 每个改动同时落代码、领域/接口合同、测试和证据；不可仅生成空壳 Adapter、OpenAPI 类型或 mock 服务器声称能力已完成。

## 三、必须完成的 P0/P1

P0：保持旧 MCP/信任边界和已验收 Codex/OpenCode 通路；实现或核实当前版本的能力/证据分离、输入准入（含 busy/approval/draft）、接收绑定 fence、Native 可能副作用的操作调和、具备条件的安全唤醒与恢复、跨机失联处理和最小诊断。**未具备原生资格的操作必须明确 `unknown`/`unsupported`，不能模拟原生安全性。**

P1：在不重新接管 Native Chat、工具、Diff、审批、模型、Worktree 的前提下，提供可信 HTTP facade、只读 Conversation 投影、联系人、消息历史与回复关系、投递/接收端/通知查询、可重放的事件同步、最小 native linkage、Orca 宿主端口与 headless consumer。插件公开接口不可用则给出稳定 port + 真实授权与协议测试 + host gap，不声称已完成宿主接入。

P2：仅记录已有现状、继承安全不变量、保留兼容；附件二进制服务、个人已读、偏好、草稿、全文检索等**不阻塞 P0/P1**。如已有 P2 通过，照常保存。

## 四、严禁更改的语义

- Client 是受信 Client，不是“任何没有 Session 的 Agent”；显示名、消息正文、模型输出不授予 sender 和管理权限。
- 普通发信不需要 Task、Run、Dispatch；Root/Route 属责任/授权范围，不能篡改私信可见性。
- `activation=message_only` 不 Native 唤醒，`sync` 只控制等待；等待超时不取消通信；正文读取不消费 Inbox。
- Native 输入成功、Provider 完成、UI 展示和用户已读都不是 Agent 的显式 `reply_to`。
- unknown 原生副作用不能盲目重发；新 Session 不得隐式承担旧 Session 的未知输入；所有接收动作受运行时再授权和真实绑定校验。
- Source 数据和客户端展示的权限不扩大；原生输入所有权永远只属于当时受信的 Host/Receiver。

## 五、验收分开，不互相冒充

`CORE_P0_QUALIFIED`：按本版 P0 场景保留真实旧路径与新增强路径证据，支持组合逐项注明。`CLIENT_P1_CONTRACT_READY`：必要通信 facade/事件/集成边界可由真实服务消费。`ORCA_HOST_QUALIFIED`：仅当特定 Orca revision/插件权限/Host 实际接通并通过时才可声明。P2 按功能单列，不计入 P0/P1 失败。

保留失败历史，区分 package static、unit、controlled integration、native protocol、independent Agent E2E 与 actual Orca host。缺失外部机器/凭据时继续其他工作，在最后列明未资格化项。没有生产授权，不部署/升级真实生产、不发真实用户消息、不合并/发布/创建 Tag/上游 PR。

## 六、交付

在 ACS 工程分支保留实际代码与证据；输出 `handoff/FINAL_REPORT_TEMPLATE.md` 规定的 P0/P1 分项结论、`adoption-state.json` 和范围差异记录。**不要等待用户确认开发阶段，不要要求重新交付上一版进度。** 发现无阻塞项即可接续当前实际待完成工作。
