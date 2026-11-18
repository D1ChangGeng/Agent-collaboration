# Orca 优先采用：Core 必要性与最小机制审计

日期：2026-11-06。独立架构研究；未安装或启动 Orca、未运行模型、未进行 GUI/实机互通。下列反例均为后续验收设计，不是已测失败。

## 判断

**目前没有用户需求与能力反例足以证明必须继续使用 ACS Core；原版 Orca + Skills／配置应是能够正式通过的完整结果。** 已检查源码包含真实持久通信与独立于provider的会话身份；用户指定机器与Harness组合仍待实机验收。

判断顺序应固定为：真实任务 → 原版能力 → Skills/配置 → 小插件实证 → 必要时最小补丁或外部组件。不能从 ACS 已有表、API、实体、安全合同倒推出新系统的需求清单。ACS 历史投入、接口兼容、模型名字不同，都不是保留 Core 的证据。

“必须由硬机制保障”与“必须由 ACS Core 保障”是两个问题。持久性、去重、认证、失效消费者拒绝不能靠 Prompt，但 Orca、操作系统、已有私有网络与凭据系统均可能是足够的责任主体。**Core 与 Fork 也不是同一选择**：外部通信缺口可能用很小的桥接器解决；左栏布局限制可能只需要上游贡献或小补丁，两者都不自动要求另一个通信 Authority。

## 证据与限制

- ACS 当前源码基线：`codex/core-cleanup@19d7881d49ee887315c54c5bc02e0cc424061376`。主要读取 [communication contract](D:/Chatgpt/Agent-collaboration/docs/runtime/COMMUNICATION.md)、采用材料和固定Orca原文；本报告不作运行环境可用或干净工作树声明。
- 本次架构核对的Orca原文固定于`9055eb9344dac1300311337cb1f0040d8094e3c2`，采用已采集一手源码。新main `52b8a24d275fe0cb598abb54119426712fae7a70`的比较与插件／worker变化由本轮插件审计单独记录；两者均未当作已安装发行版。
- Pi 旧地址 `badlogic/pi-mono` 经官方 GitHub 重定向至 `earendil-works/pi`。直接通过 GitHub connector 读取 main identity，并按 `36142c1c7eab1d756e977b5f39149a634cc472ac` 重新采集 README、extensions、skills、containerization；原文保存在本目录 `sources/pi/`。
- [Orca 远程服务器官方文档](https://www.onorca.dev/docs/remote-servers)支持服务器拥有状态、客户端可撤销配对与私有网络路径；这是公开合同，未替代实机验收。编排官网页面本轮再次打开失败，编排结论依据固定源码，不依赖该页面成功加载。

## 需求分层矩阵

“保留 Core 触发条件”均是**必要证据条件**，不是条件出现后必须整套保留；仍要比较插件、窄桥接器与 Core 的实现/运维成本。每项反例只验证所列保证，不承诺 exactly-once 任意外部副作用。

### A. 原始必须价值：单人、多机、多 Harness、长期开发、明确通信与恢复

| 真实价值/最小要求 | 所需保证与责任主体 | Orca / extension 一手事实 | Prompt / Skills 责任上限 | 保留 Core 的证据门槛 | 最小实机反例 |
|---|---|---|---|---|---|
| A1 在本地和远程机继续开发，Agent 不随前端断开丢失 | 服务器拥有执行与状态；认证连接；恢复有可读结果。可由 Orca + 私有网络承担 | 官方 remote-server 合同区分完整远程运行时与 SSH workspace；每配对客户端有可撤销 token；重连返回服务器状态 [O1] | 说明在哪台主机操作、凭据安装在哪里；不能让进程持久或建立认证 | 用户实际 OS/网络/Harness 必须组合在原版中失败，且既有部署配置与小适配无解 | 远程 Agent 执行可验证的文件任务，前端断网/重启后重连；结果与原 session 继续可读，无多起副本 |
| A2 同项目多 Agent 分工并收回报告 | 委派对象、生命周期、任务结果和消息可区分；不必有 ACS 专属实体 | durable Run/Task/Dispatch、workerStart、workerDone、消息与远程 federation 已有实现 [O2,O3] | 任务切分、角色分工、质量标准、何时寻求帮助；不能保证 dispatch 原子提交 | 一项用户常做的并行任务无法完成，原因是运行时能力缺失而非术语不同 | 两个不同 Harness 并行改互不冲突文件，分别报告；协调者能追溯各自来源、继续追问 |
| A3 明确“谁在回复哪条请求”，工作完成与回复分开 | 原消息 ID、作者与关联原文可重读；运行完成不应被误当明确回复 | Message 有 thread_id；Question 有 answer_message_id/body/generation；send/ask 为不同合同 [O2,O4] | 要求每条答复引用 request handle，写明确认/澄清/完成；文字引用不能独立保证真实作者或持久关联 | 真实流程需要的原文关联无法由 thread/ask 合同表达，并造成错误的完成判断；先验证轻封装 | 同一 peer 连续提出两问，先回复第二问，再澄清第一问；重启后仍能判定各问状态 |
| A4 断线后恢复历史与未完请求，不凭摘要猜测 | 持久原文、顺序/游标、读取/投递区分；日志责任属于运行时 | SQLite 消息存储、sequence、inbox history/peek、delivery/read 区分与 consumer generation 已实现 [O2,O5] | 启动时查 Inbox/history、保留 handles、从原文恢复；不能恢复从未写入的数据 | 原版在用户实际重启/清理周期内丢失必需原文/关系，或无法可靠发现未完通信 | 一条消息提交后关闭消费者，重启读取原文；翻页期间再收一条，检查无永久遗漏 |
| A5 重试不会静默重复启动或重复提交同一通信 | 稳定请求身份、持久 receipts、事务/副作用边界、未知结果可读；不要求任意动作 exactly-once | send 路径读取 mutation receipt、执行 replay nudge；源码有去重与 consumer fencing [O3,O5]。精确故障语义须实测 | 保留原请求 ID，不因超时编造完成或盲目重发；不能让文本相似性成为幂等键 | 在实际网络故障下出现无法识别的双 dispatch/重复动作，且原版 retry API/配置或窄包装无法修复 | 提交时切断响应链路，以同一原请求身份重试；检查 message/dispatch 与 native 启动次数，保留 unknown |
| A6 长期联系同一协作者，换/清会话不误投 | 先明确“同一协作者”需求；长期地址到当前接收者的可核查映射、旧消费者不得冒领 | Orca structured session ID 独立于 provider；/clear 保留 lineage-root；PTY 无此 ID，不可用 pane 等同长期身份 [O6] | 可保存人类名称→当前地址的 metadata，并显式交接；不能让别名自动成为受信身份 | 用户确需跨 run、provider 或机器替换后保持同一可授权地址，而 Orca lineage/轻量映射无法满足 | structured 会话 /clear 后继续发原地址；再跨 provider/机器更换。分别检验能力，不把一个成功扩成所有组合 |
| A7 独立 Harness 能读上下文、发消息并继续工作 | 支持的实际 CLI/MCP 接口、调用者上下文、可读错误；同人拥有环境可沿原版信任边界 | Run/Dispatch caller 从实际上下文解析；send 不把 caller 参数当 lifecycle authority；已有 CLI/RPC 与 federation [O3,O7] | Skills教调用现有工具、解释错误、给出上下文与来源；不能凭 Prompt 注入调用权限 | 用户指定独立 Harness 必需操作被原版真正拒绝/缺失；用其现有 CLI/MCP 接入和配置仍无解 | Codex/OpenCode 各自从自身进程调用，分别发问、读原文和显式答复；不得由测评脚本代替 Agent 回答 |

A1—A7 的价值必须保留；它们所用的 ACS API、表结构与概念没有继承义务。A6 的“跨任意 provider/机器保持固定个人联系人”属于仍需用户任务证明的强版本；普通长期开发可以采用原生 session、run 和明确交接。

### B. 条件性需求：真实外部调用、不可信主体、权限隔离

| 条件需求 | 所需保证 | Orca / extension 事实与未知 | Prompt / Skills 责任上限 | 保留 Core 的证据门槛 | 最小实机反例 |
|---|---|---|---|---|---|
| B1 网页 Agent/独立应用直接访问开发系统 | 已认证调用者、可撤销最小权限、正确的读写/执行范围；按实际入口选 OAuth、配对或网关 | 原版有远程配对与撤销 [O1]；它不自动等于任意远程 MCP Client 的细粒度授权。trusted-worker 能承载外部适配，但不是现成受限远程 Agent API [O8] | 指示何时调用、向哪个受权对象发消息；不能把正文里的 sender/role 当认证 | 用户确认必须使用某外部网页入口，完成该入口真实 auth/撤销/重连探针后，原版和窄插件仍缺必要能力 | 给网页调用者只读或限对象权限；越权发送/读取与撤销后重试均应拒绝，合法消息仍可恢复 |
| B2 同一系统中多个互不信任 Agent 的私信隔离 | 服务端按真实参与者/范围授权原文与历史读取，非 UI 隐藏 | Orca 存在实际 caller/run/scope/fencing [O5,O7]；未证明等价 ACS 每 Slot/参与者 ACL，不能宣称缺失或等价 | 规定不要读取不属于任务的历史；不是防恶意读取的边界 | 存在实际不可信身份/机密隔离需求，原版恶意读取测试失败，且其配置/插件网关不能完整封闭入口 | 第三身份拿到 message/thread ID 直接调用 read/history；不能读另两身份私信正文 |
| B3 模型/工具/插件不能接触其他项目文件与凭据 | OS/容器/网络/凭据边界，覆盖所有执行途径 | sandboxed-ui 与 trusted-worker不同：后者拥有普通 Node 能力；host capabilities约束 host API，不等于OS沙箱；hook覆盖有限 [O8,O9] | 减少暴露上下文、教合理用工具；不能限制任意代码直接读盘/联网 | 用户确需敌对代码强隔离时，首先验证宿主沙箱/VM；Core 本身也不能代替OS隔离 | 受限 Agent 从 shell、任意 Node、插件和远程工具尝试读未挂载 secret/写别项目，实际 OS 拒绝 |
| B4 审核/角色权限/Root–Route 分权需要强执行 | 只有明确独立安全主体时需受信管理身份、撤销/旧绑定拒绝、服务端检查 | 原版已有配对授权与 caller fencing；插件 hook 可在覆盖路径检查，不能冒充所有路径的全局权限层 [O1,O7,O9] | “Reviewer 不改代码”“Route 管理职责”等单人流程约定可用 Skills；无法认证 manager | 用户确需别人或不可信Agent受限地管理/发送，具体越权反例证明需额外 authority | 将 reviewer 权限降级后，旧调用上下文重试管理操作；检查服务端拒绝及允许的沟通仍工作 |
| B5 签名、重放、时钟、逐级事故通知、强审计 | 只为明确威胁/事故恢复目标选择；需覆盖实际接收与副作用点 | Orca federation 有 runtime epoch、peer fingerprint、seq/ack/receipt [O2]；未作完整安全审计。现有 ACS 更强合同不自动产生需求 | 可规范事故报告/手动升级/证据格式；不能验证签名、可靠计时、封闭重放窗口 | 已发生或可重现的真实威胁/恢复成本，不能由既有私网/运行时机制合理缓解 | 针对已选择的威胁，只做一条具体负向 probe；例如旧 epoch 重放被实际接收入口拒绝 |

单人 owner 环境依然需要基础远程认证与凭据保护（A1），不能把它们一起降为可选。B 类强版本应在需要时引入；不应预建完整多租户治理系统。

### C. 组织、角色、Route、规范与知识

| 需求 | 最小保证 | Orca / extension 事实 | Prompt / Skills 责任上限 | 保留 Core 的证据门槛 | 最小实机反例 |
|---|---|---|---|---|---|
| C1 Project/Route 长期组织 | 稳定 metadata + 可读文件/Git + 路径可发现；不是必然服务端实体 | 原版有 ProjectGroup 与层级/folder workspace；插件可列出/打开跨主机 workspace，private storage 可存映射 [O8,O10] | 解释 Route 的责任/知识/目标与工作区映射，读取当前资料 | 单纯分组/名称不支持 Core；只有真实必需的受信跨入口组织授权失败才考虑 B4 | 原版 group + Route 文档跑一周真实任务；观察是否有错误打开/丢上下文，而非比较字段名 |
| C2 Coordinator/Executor/Reviewer 与验收程序 | 可查职责、清楚交接、验收证据；独立安全主体另归 B | 可沿已有 run/workers，或安装组织视图插件；不需复制 Task Authority | 分工、审查、验收推理、手动决定和证据标准适合 Skills | 角色不等于 Core必要性；需要硬权限时先证明 B4 | 换新会话后仅用项目文件和skills能否按职责继续正确任务 |
| C3 知识、交接、源代码基线、同步规范 | 文档/Git为权威，版本证据可重查 | editor/workspace/原生开发闭环可复用；插件 editor.open与workspace.list/open能提供入口 [O8] | 记录来源、提交与测试结果、提醒fetch/pull；不能让消息自动同步另一个clone，也不能保证模型永不忘 | 文档不便读取先改路由/插件入口，不引入通信Core；需要强证据签核时另证明业务价值 | 新会话只凭handoff恢复目标、准确commit及未完项；故意给旧SHA时应自行核对并停止错误结论 |
| C4 组织面板/左栏偏好 | 用户能找到对象并完成工作；视觉位置须有真实体验收益 | 插件可做右sidebar panel、worker、storage、settings、secrets；任意左sidebar贡献reserved；原版分组已存在 [O8,O10] | 可说明入口位置；无法改变应用导航 | UI偏好不触发Core。先右panel试用；只有真实任务证明原版groups/面板不够，再向上游提API或窄fork | 同一真实任务比较原版groups与右panel的找对象/切换；不能仅凭想象认定一定要左树 |

## Pi 的“小核心”到底可以借鉴什么

Pi 官方 README把具体工作流定制交给 extensions、Skills、prompt templates和packages，并明确把 subagents、plan mode列为可另装的工作流选择。可借鉴的是**将可替换的工作策略放在扩展层，保持机制与策略边界**，不是把每个功能换成Prompt。[P1]

Pi extensions是执行中的 TypeScript 代码：可注册工具、事件/阻断hook、UI与commands，并通过 appendEntry保存状态。它们与普通Skills不同：代码承担确定行为，Skills告诉模型如何工作。官方也明确扩展运行在宿主进程且拥有相同OS权限；trusted extension不是隔离主体。[P2]

Pi公开说明默认无内建文件、进程、网络和凭据的权限限制；有强边界时采用沙箱/容器。容器化文档特别区分“整个进程隔离”与“只将若干工具转入VM”，后者无法约束仍留在宿主的扩展工具。这个例子支持把安全保证放在真实执行边界，而不是证明无需安全机制。[P1,P3]

据此，本项目最小原则应为：

1. 优先复用 Orca 已有机制，而不是建立“更小的第二套Authority”。
2. Skills拥有工作流语义、职责、检索、上下文与验收推理；它们不拥有持久事务、认证、幂等或原文真伪。
3. 插件先承接轻量metadata、导航、模板和适配；需要稳定写入时用真实storage/code，明确数据归属。
4. 一旦插件开始重建独立地址/消息日志/Outbox/权限服务，它已是新运行时，应重新评估是否真的需要。
5. 小核心不是代码行数目标。当前Pi仓库也包含独立durable runtime包；不要把项目口号解释成“所有长期状态都不重要”。[P1]

## 本阶段应列为 optional 的 ACS 强保障

以下是已有合同/机制的价值，不等于目前有真实使用证据要求在新底座中全部保留：

- 固定 ACS API、handle spelling、Project/Root/Route/Slot 数据模型与存储形态。
- 任意 provider/host/session替换仍保留同一 AgentSlot 的强连续性；若原版 lineage与显式交接足够，就无需泛化。
- 一条回复必须同时关联多个原文的 reply_to[]。先验证thread/ask与一条摘要引用是否已满足工作；只有用户确需可查询多原文关系时再加小关系索引。
- 单人环境中细分 Client/Root/Route manager管理层级、逐Slot principal/Grant、完整参与者私信权限；遇到真正不可信主体时再升级。
- 完整跨主机签名/时间窗/部署Profile覆盖、精细管理并发修订、逐级事故通知链、旧协议adoption兼容矩阵。
- 为旧服务无缝续用而常驻两套消息/任务状态机；除非迁移存量数据的真实代价超过收益，否则历史可保留为只读档案。

这些项目不是“删除已有安全性”的建议。它们约束的是新采用路线的新增复杂度；旧部署按其既有合同运行，是否退役另需具体数据/依赖盘点与迁移计划。

## 可执行的最小采用门槛

先挑一个代表用户实际工作的短任务：一个仓库、当前本地与远程主机、两个实际常用Harness；包含分工、明确答复、断开重连、读历史和下一天继续。先用原版groups、原生orchestration/CLI与现成Skills完成，不要求映射任何ACS术语。

每个缺口记录：用户要完成的动作、精确版本/机器/调用入口、预期/实际、保存的日志或状态读回、配置更正、插件尝试、剩余维护成本。**没有反例记录就不能把“Orca不支持”升级为Fork或Core理由**。源码可先证明某已列API不存在，不应把未实测的运行场景写成失败。

第一插件如有必要，可先做Route文件／知识入口、workspace映射、明确handoff模板与原生对象链接，验证复用原版消息与执行的最小路径。是否接入Core按已证实缺口另决。插件卸载后，原生项目与任务仍应可读。

插件试验若不能满足需求，再分别选择：向上游贡献/请求公开API；维护很小的补丁；只服务已证实外部入口的适配器；或保留Core。只要原版加Skills已满足代表任务，本阶段就应收敛并停止扩建。Core可以最终取消。

## 一手来源

- [O1] [Orca Remote Servers官方合同](https://www.onorca.dev/docs/remote-servers)，2026-11-06读取；约束：公开文档，不代表本地已验证。
- [O2] [Orca orchestration types](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/types.ts)、[federation runtime](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/runtime-orchestration-federation.ts)。
- [O3] [send methods](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/rpc/methods/orchestration/messaging/send-methods.ts)、[workers](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/rpc/methods/orchestration/worker/workers.ts)。
- [O4] [ask methods](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/rpc/methods/orchestration/messaging/ask-methods.ts)、[agent message relation](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/agent-message-relation.ts)。
- [O5] [mailbox consumer](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/db/messages/mailbox-consumer.ts)、[message inbox](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/db/messages/message-inbox.ts)、[SQLite orchestration DB](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/db/orchestration-db.ts)。
- [O6] [Orca session address](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/shared/orca-session-address.ts)。
- [O7] [caller identity](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/orchestration/orchestration-caller-identity.ts)、[run scope](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/main/runtime/rpc/methods/orchestration/runs/run-scope.ts)。
- [O8] [plugin authoring](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/docs/reference/plugin-authoring.md)、[plugin host API](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/docs/reference/plugin-host-api.md)。
- [O9] [hooks合同](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/docs/reference/plugin-host-api.md#hooks)：默认错误放行，可逐hook设onError=deny；手工输入不被拦；tool-before仅Claude Code可阻断，SSH/WSL不覆盖。不是通用隔离层。
- [O10] [ProjectGroup types](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/shared/project-group-types.ts)、[panel contribution](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/shared/plugins/contributions/plugin-panel-contribution.ts)、[contribution points](https://github.com/stablyai/orca/blob/9055eb9344dac1300311337cb1f0040d8094e3c2/src/shared/plugins/contributions/plugin-contribution-points.ts)。
- [P1] [Pi root README](https://github.com/earendil-works/pi/blob/36142c1c7eab1d756e977b5f39149a634cc472ac/README.md)、[coding-agent README](https://github.com/earendil-works/pi/blob/36142c1c7eab1d756e977b5f39149a634cc472ac/packages/coding-agent/README.md)。
- [P2] [Pi extensions](https://github.com/earendil-works/pi/blob/36142c1c7eab1d756e977b5f39149a634cc472ac/packages/coding-agent/docs/extensions.md)、[Skills](https://github.com/earendil-works/pi/blob/36142c1c7eab1d756e977b5f39149a634cc472ac/packages/coding-agent/docs/skills.md)。
- [P3] [Pi containerization](https://github.com/earendil-works/pi/blob/36142c1c7eab1d756e977b5f39149a634cc472ac/packages/coding-agent/docs/containerization.md)。

