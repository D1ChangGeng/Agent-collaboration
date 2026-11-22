# ORCA 优先采用：能力评估与路线决策

状态：现行架构研究基线。日期：2026-11-06。

本文件是 Client 方向唯一现行决策来源。当前决定以完整 ORCA 宿主为基础，先评估原版能力与 Core 必要性，再按实测缺口选择 Skills／配置、插件或 Fork。产品形态、Core 最终去留和插件实际可行性仍待能力试验形成证据。

## 1. 已确认原则与研究状态

以下路线原则已确认，可直接指导研究和后续试验：

1. 继承 ORCA 已有成熟设计、交互和实现，以完整应用承载开发工作。
2. 先做用户需求与原版能力对照；优先采用原版 + Skills／配置。
3. 原版存在实际缺口时，优先验证 **ACS as ORCA Plugin**，适应原生 panel、commands 等交互。
4. 只有插件验证后仍有关键需求无法满足，才评估基于 ORCA 的 Fork；按证据选择一条路线推进。
5. Core 是否需要单独评估。原版、插件均允许最终采用不依赖 Core 的方案；Fork 候选可暂沿用现有 Core 设计，仍须接受能力对照与必要性检验。
6. 当前阶段交付能力评估、架构判断与验收方案。下一步是固定版本实机试验。

原版 + Skills、轻插件、Fork，以及其中按实证保留 Core 的组合，都是有效结果。是否 Fork 与是否保留 Core 是两个独立决定。

**当前证据结论：尚无用户关键需求与能力反例足以证明必须保留 ACS Core；也尚无实机证据证明可以安全完成现有部署的退役。** 因此保持当前运行系统，采用研究允许 Core 最终取消，不据此移除代码、数据或安装。

### 证据基线

| 对象 | 固定基线与已知范围 | 证据限制 |
| --- | --- | --- |
| ORCA | `52b8a24d275fe0cb598abb54119426712fae7a70`；插件审计保存官方文件与来源索引 | 静态源码与公开合同；未安装启动，未连接真实模型／Agent |
| 前轮 ORCA | `9055eb9344dac1300311337cb1f0040d8094e3c2`；本轮比前轮 ahead 5、behind 0 | 插件与 send/check/ask 关键面未改；worker stop/release receipts 有变化，相关旧证据需复核 |
| ACS | 2.3.1；源码 HEAD `19d7881d49ee887315c54c5bc02e0cc424061376` | 现有机制是比较对象，不自动成为新底座必选要求 |
| Pi | 官方仓库 `earendil-works/pi`，固定 `36142c1c7eab1d756e977b5f39149a634cc472ac` | 用于机制／策略边界参考，不是 ORCA 运行能力证明 |

本篇将“已确认原则”“源码／官方合同事实”“能力组合推论”“运行待验”分开使用。源码中存在能力不等于本地验收通过；没有公开插件 API 也不等于整套应用缺少该能力。

详细材料：[插件能力审计](orca-first-20261106/plugin-audit/plugin-capability-audit.md)、[官方源码索引 P01—P35](orca-first-20261106/plugin-audit/source-index.md)、[Core 必要性与 16 项需求分层审计](orca-first-20261106/architecture-audit/REPORT.zh-CN.md)。

## 2. 从用户价值确定最小要求

当前目标是一个用户在多台机器、多个 Harness 中长期开发，能明确委派与通信，并在断线和换会话后继续工作。验收比较真实行为与结果，不要求复制 ACS 的术语、协议、字段或存储表。

| 优先级 | 必须保留的用户价值 | 最小可观察结果 |
| --- | --- | --- |
| Must | 多机继续开发 | 本地与远程机器上的执行和状态归属明确；前端断开后可认证重连、找到任务与结果 |
| Must | 多 Harness 分工 | 两个实际使用的 Harness 能领取不同任务、报告来源、继续追问，结果不会混淆 |
| Must | 明确通信 | 可以辨认真实发送者、原问题与明确答复；任务结束、消息提交、对方答复各有清楚含义 |
| Must | 历史与恢复 | 能重读原文、找回未完成请求；恢复依据持久记录与可核查对象，而非只凭摘要 |
| Must | 有界的重试与接收归属 | 超时结果可判定或明确未知；同一操作重试有可解释结果，旧接收者不能冒领新归属 |
| Must | 会话接续 | 常用的清会话／重开会话流程能恢复工作；身份与地址变化可发现、可交接 |
| Must | 组织与知识可发现 | Project／Route、职责、Skills、交接与源码基线有稳定入口，新会话能据此继续 |

多机目标包含基础远程认证与凭据保护。其余强安全要求按真实使用条件加入：

| 条件需求 | 何时成为要求 | 要验证的边界 |
| --- | --- | --- |
| 外部网页 Agent／独立应用直连 | 用户确需从该入口读取或操作开发系统 | 调用者认证、最小权限、撤销与恢复；不能由消息正文声明身份 |
| 互不信任主体的私信隔离 | 不同身份确有不可互读的原文与历史 | 服务端授权覆盖直接 read/history，UI 隐藏不足以证明隔离 |
| 恶意代码与跨项目凭据隔离 | 要运行不可信 Agent、工具或插件 | OS／容器／网络边界覆盖实际执行路径 |
| 强制管理分权 | 角色确为独立安全主体，而非单人工作职责 | 降权／撤销后旧上下文被真实入口拒绝 |
| 签名、重放、强审计与事故链 | 有明确威胁、合规或恢复成本依据 | 针对所选风险的接收、副作用与恢复边界 |

固定 AgentSlot 跨任意 provider／host 的连续性、`reply_to[]` 多原文关系、细分 Grant 层级、旧 API 兼容和完整部署矩阵，目前属于条件性能力。先验证原生 lineage、thread／ask、配对与明确交接是否足以完成实际任务。

## 3. 原版能力对照：实现事实与实机结果分轴

下表“存在”仅表示可读源码或官方合同提供依据。“待验”保持独立，避免将源码发现写成验收结果。架构审计保留前轮固定源码出处；本轮比较更新了插件与通信关键面的适用边界。

| 用户动作／能力 | 原版事实与来源 | Skills／配置或插件可补充 | 实机状态与关键问题 |
| --- | --- | --- | --- |
| 远程继续开发 | 官方远程服务器合同：服务器拥有执行／状态、客户端配对可撤销；架构审计 O1 | 主机选择、凭据部署、重连指引 | 待验：当前 Windows／远程 Linux、网络和 Harness 组合；SSH workspace 与完整远程运行时须区分 |
| 并行委派 | 有 durable Run／Task／Dispatch、workerStart／workerDone、federation；O2—O3 | 任务拆分、职责与报告标准 | 待验：两个实际 Harness、跨机器委派、取消及回收；当前 stop/release 变化需复核 |
| 发问与明确答复 | Message 有 thread_id；Question 有 answer_message_id/body/generation；send 与 ask 分开；O2、O4 | 明确答复约定、请求 handle 的可读呈现 | 待验：乱序答复、澄清、超时与任务完成不会互相冒充 |
| 历史与接收恢复 | SQLite 消息、sequence、inbox history/peek、delivery/read 与 consumer generation；O5 | 恢复时检查历史与未完请求 | 待验：重启、翻页期间新消息、读／确认语义、保存周期与真实状态归属 |
| 重试与旧接收者拒绝 | send 有 mutation receipt、replay nudge、去重和 consumer fencing；O3、O5 | 保留原请求身份，展示未知结果 | 待验：响应丢失后重试、重复 dispatch、过期消费者拒绝；不承诺任意副作用 exactly-once |
| 长期会话地址 | structured session ID 独立于 provider；/clear 保留 lineage-root；PTY 不具有同等 ID；O6 | 名称与当前原生地址的映射、明确交接 | 待验：清会话、换 provider／机器分别测试；terminalId 不作永久联系人 ID |
| 独立 Harness 调用 | 有真实 CLI/RPC、caller/run scope 与 federation；O3、O7 | 各 Harness 加载原生操作 Skills 与配置 | 待验：从各自真实进程发现连接、认证、发送、读取和答复 |
| 组织、Route 与知识 | 原生 ProjectGroup 层级、workspace／editor 入口；P01、P27 | 先用原生分组与文件；必要时插件保存角色／Route 映射 | 待验：找对象、切换与恢复；ProjectGroup 类型存在不等于公开插件 CRUD |
| Skills／MCP | 有原生 skill inventory、bundled registry 安装路径、MCP 配置检查；P32—P34 | 按 Harness 的原生机制组织资料与配置 | 待验：实际发现／加载／调用；插件 skills/mcpServers 贡献点仍是空槽 |

由此可以推论：ORCA 已承担相当一部分通信与执行机制，不能将其预设为仅有界面的外壳。上述事实也不能证明它已满足用户全部机器、入口与恢复场景。

## 4. 机制、策略与扩展的责任

认证、持久写入、重试去重、原文关联和 fencing 必须由可执行机制保障；责任主体可以是 ORCA、现有操作系统／私有网络、必要的适配器或 Core。先确认谁已提供，再评估缺口。

| 责任层 | 适合承接 | 能力边界 |
| --- | --- | --- |
| ORCA 原生运行时与现有基础设施 | 连接认证、状态归属、消息原文、请求身份、事务／回执、接收者代际 | 逐项实测其实际保证，不从 API 名称推断等价性 |
| Skills／Prompt／项目文件 | Coordinator／Executor／Reviewer 职责、任务拆分、检索、交接、验收推理与组织约定 | 不能认证作者、让丢失数据复原、建立事务、阻止任意越权调用 |
| 插件代码 | 确定性 metadata、导航、模板、状态读回、有限适配与覆盖路径内的 hook | 以公开 API 和真实执行边界为准；增加代码不自动产生可靠通信或安全隔离 |
| OS／容器／凭据系统 | 不可信代码的文件／进程／网络／secret 隔离 | Core 与 UI 均不能替代实际执行环境的隔离 |

**Pi 官方事实：** 其 coding-agent 将工作流定制交给 extensions、Skills、prompt templates 与 packages；extensions 是执行中的 TypeScript，可注册工具、事件、UI、commands 并保存状态。官方同时说明扩展具有宿主进程的 OS 权限，强隔离应使用容器／沙箱。见[固定 Pi 原始材料与出处](orca-first-20261106/architecture-audit/REPORT.zh-CN.md)。

**本项目推论：** 借鉴可替换策略与确定机制分离，优先复用宿主；“小核心”不能解释为用 Prompt 替代可靠机制。Pi 的扩展模型也不能外推成 ORCA 插件的具体权限合同。

## 5. ACS as ORCA Plugin：可继承面与接入边界

插件首先适应 ORCA 的原生交互。右侧 panel、原生命令、快捷键、通知、状态与现有工作区导航，是当前可验证的承载面。顶部／左侧专用布局尚无公开贡献点，本身尚不构成用户目标的阻塞证据。

| 范围 | 固定版本事实 | 插件准入与运行待验 |
| --- | --- | --- |
| 组织与知识入口 | 右侧 HTML/components panel；Tree、Table、Tabs、Textarea、Markdown 等原生控件；P03—P04 | 优先承载 Route／角色资料、Skills 目录、交接与原生对象链接；测真实查找与切换成本 |
| commands／events／hooks | 命令、快捷键、statusbar、通知；workspace/agent 事件；8 类 hooks 已实现；P01、P06—P10 | hooks 默认错误放行，可按覆盖路径设 onError:deny；手输、restore、非本机 Claude Code 等存在覆盖限制 |
| storage | 插件各 surface 共享的自有磁盘 KV；256 KiB/value、5 MiB/store、1024 keys；P23—P24 | 适合 metadata；不是跨主机／多端同步合同。需验证存在哪台 host、重启／重装与备份恢复 |
| secrets | 自有 vault；无可用 OS 加密或 Linux basic_text 时拒绝写入；P25 | 使用 secrets API 并检查失败；静态保护不等于对同账户 full-access worker 的隔离 |
| worker | 可使用可信 Node worker；环境白名单、代码与当前同意检查；P12—P22 | full-access 进程拥有普通 Node 能力；可运行 CLI 的推论不等于通信接入已打通；worker 生命周期也不提供持久消息队列 |
| terminal／agent | workspace.list/open、terminal.create/sendText/read、agent.launch；P01、P26 | 保留真实 workspace／terminal target；launch 返回 terminalId 后异步提交 prompt，失败仅日志，不能作为 delivery receipt 或完成证明 |
| native mail | 公共 Host API 没有 orchestration.send/check/ask，也不暴露 raw RPC；真实 CLI handlers 存在；P02、P28—P31 | 直接通信 adapter 单独验证；消息入口能渲染，不证明原生 mail 闭环已建立 |
| CLI 身份与连接 | worker 环境白名单剔除 ORCA_*；CLI 有 caller identity 解析与无身份拒绝；P14、P31 | 必须证明插件进程能取得合法真实上下文和端点；不能伪造／借用其他 pane 身份绕过入口 |
| Skills／MCP 衔接 | 可组织 metadata；原生 inventory／配置存在；插件 contributes.skills/mcpServers 保留空槽；P07、P32—P34 | bundled registry 安装不等于任意包安装；按实际 Harness 验证加载，不承诺插件注入 |
| 宿主权限入口 | 每次 Host API 调用检查 surface／capability／consent、严格参数；mutation attempt audit 与实时撤销复查；P15—P17 | 保证适用于该入口；能力清单不会约束 worker 直接 Node 文件／网络／子进程调用 |

桌面 UI guest 有独立 process／origin，不提供 Node，并在 Electron session 层限制网络；浏览器客户端采用不同且较弱的 frame 路线。UI frame 隔离、worker 崩溃隔离与 OS 访问权隔离必须分别表述，不能互相代替。P18—P19。

源码与文档有一处已知冲突：authoring 尾段把 hooks 列为 planned，而当前 schema、实现与生成 API 已包含 hooks。当前事实采用后者；agentHarnesses、skills、mcpServers、taskSources、connections、sidebarCards 仍为 reserved。P05—P11。

第一项插件试验可以只提供组织／知识／交接入口，带用户进入原生 Agent 与 Skills 工作流。只有真实任务需要插件直接通信时，才试验受控 CLI／其他公开接入；不预建第二套消息、地址、Outbox 或权限 Authority。

## 6. Core 必要性：保留门槛与现有部署

目前证据支持“Core 可取消”作为正式有效结果，尚不支持“Core 已可退役”的运行结论。资料存储、组织树、长角色说明和入口导航，本身不构成保留 Core 的必要性；缺公开插件通信 API 也不自动推出必须保留 Core 或 Fork。

保留 Core 必须形成一条完整证据链：

1. **用户动作：** 指出哪个实际必须动作无法完成，及丢失该动作的成本。
2. **原版反例：** 固定版本、机器、Harness、入口、预期／实际与可重现日志，排除配置问题。
3. **插件边界：** 已按公开 API 验证所需接入，记录剩余缺口，避免仅凭布局或字段不同作结论。
4. **机制差异：** 指明缺的是认证、持久原文、关联、撤销、恢复还是身份连续性，并证明 Core 可补齐。
5. **成本比较：** 比较原版配置、轻插件、窄适配、上游改进、Fork 与 Core 的长期维护成本，选择最小足够方案。

可能触发这条评估的需求包括：实际外部入口的可撤销权限、互不信任主体的原文隔离、常用替换流程中的稳定授权地址，以及原版实测无法提供的持久恢复语义。它们都需要具体任务与反例，不能仅因 ACS 已实现而保留。

当前 Core 的代码、安装、运行合同与存量数据继续按既有责任维护。若未来决定退役，另行盘点真实依赖、数据归档／迁移、凭据撤销与回退路径；本篇归档范围仅涉及旧 Client 产品材料。

## 7. 路线决策与停止条件

| 阶段 | 进入依据 | 过关结果与停止条件 |
| --- | --- | --- |
| 0．原版能力／Core 必要性评估 | 本篇需求分层与固定源码证据 | 输出代表任务、待验能力和证据记录；确认试验安装版本与源码关系 |
| 1．原版 + Skills／配置 | 优先执行代表任务 | Must 场景通过即采用并结束额外开发；Core 按实测需求另决 |
| 2．ACS as ORCA Plugin | 原版存在明确用户缺口，可由公开扩展面验证 | 插件满足关键需求即采用并结束 Fork 评估；插件允许不依赖 Core |
| 3．ORCA Fork 评估 | 插件验证后仍有关键需求无法满足，且有完整缺口证据 | 比较最小修改与维护成本；继承成熟宿主设计与实现，Core 仍接受必要性检验 |

无需为证明选型而把两条路线都开发出来。原版、插件、Fork 的进入条件由用户价值与证据推进；一次未安装、一次 API 缺失或一张静态页面不构成产品路线验收。

当插件需要维护独立消息日志、身份服务、恢复队列或授权体系时，暂停扩大插件范围，先重新审查是否确有新增运行时的必要性。其结果可以是更小的适配、Core 组合或 Fork，不自动归入任何一个选项。

## 8. 固定版本实机验收方案

以下均为**待执行场景**，不是已测通过或已测失败。先在隔离试验项目中使用用户实际的本地／远程主机和常用 Harness；初始候选组合是本地 Windows、远程 Linux 与 Codex／OpenCode，先核实其真实可用性。记录真正安装的 ORCA build 与固定 SHA 的关系。基本验收针对 ORCA 中运行的 Harness；外部独立应用直连按条件需求另验。环境缺项单独记录，不能让脚本代答。

每项记录：版本、OS／host、Harness、真实调用入口、原生对象／请求 ID、操作顺序、预期与实际、状态读回／日志、故障注入点及结果。凭据仅记作用域与状态。以已安装版本帮助与官方合同确定命令，不预设 CLI flags。

| 编号／优先级 | 具体操作 | 必须保存的证据 | 过关结果 |
| --- | --- | --- | --- |
| T01／P0 通信 | Codex 向 OpenCode 连续提出两个可核验问题；先答第二问，再澄清并答第一问 | 两条原问题、真实作者、关联 ID、明确答复原文与最终状态 | 两问可分别追溯；乱序不误配；结束任务不冒充明确答复 |
| T02／P0 并行 | 同仓库两个 Harness 分别修改互不冲突的试验文件，各自报告；协调者追问一项结果并收回答复 | run/task/dispatch 与变更、报告来源、追问关联；当前 worker 停止／回收状态 | 两项结果可区分、可继续追问；取消／回收无残留重复执行 |
| T03／P0 重连 | 远程 Agent 执行写文件任务时断开前端网络，关闭客户端，再重新认证连接 | 服务器任务状态、原 session、文件结果与重连读回 | 任务／原文可找回，状态归属明确，不因重连另起同任务副本 |
| T04／P0 历史 | 提交消息后关闭消费者；重启并读取原文；翻页时再收一条新消息 | 提交回执、sequence／cursor、read/peek/ack 实际行为与重启结果 | 无永久遗漏；能区分未读、已读与明确答复；未完请求可恢复 |
| T05／P0 重试 | 在提交响应返回前切断链路；通过受支持入口以同一原请求身份重试 | 原请求身份、mutation receipt、消息／dispatch 数量、native 启动次数 | 无静默双提交；结果可确认或明确 unknown；后续恢复有可执行路径 |
| T06／P0 常用会话接续 | 执行用户实际常用的 structured 清会话／重开流程；provider／机器替换只将用户明确必需路径列入 P0，其余作为探索 | lineage／地址变化、旧与新接收者读回、handoff 与原文；逐项标记必需或探索 | 必需接续路径完成，旧消费者不能冒领；额外组合记录为探索结果与适用边界 |
| T07／P0 基础权限 | 已配对客户端合法连接后撤销配对，再以旧上下文重连／读写 | 服务端拒绝结果与合法连接对照；不保存 token 正文 | 撤销实际生效，合法客户端仍能恢复；真实 sender 来源可查 |
| T08／P0 知识接续 | 新会话只依据项目文件、Skills 与交接继续任务；交接中放入可识别的旧 commit | 实际读取资料、Git 核对、未完项与下一动作 | 能识别基线差异、恢复职责和目标，不将旧 commit 当当前事实 |
| T09／P1 插件入口 | 仅在入口缺口成立后，使用原生右 panel／commands 完成查 Route、开 workspace、读角色与交接 | 操作过程、实际控件、空／错状态、重启前后 storage 读回、host 归属 | 可发现且可完成任务；metadata 归属与恢复清楚；多端同步另有证据 |
| T10／P1 插件 API | 在批准的 worker 中验证 terminal／agent API、撤销 consent 与 worker 重启；制造 prompt 提交失败 | Host API audit、权限拒绝、terminalId、日志与真实 Agent 接收证据 | 状态不把 terminal 创建当 delivery；撤销按合同生效；内存等待不冒充持久任务 |
| T11／P1 直接通信 adapter | 仅在需要插件直发时，从真实 worker 验证连接／身份发现，再试 send/check/ask、重启恢复；同时测试缺身份情形 | 合法 caller、endpoint 来源、消息原文与关联、消费副作用、无身份拒绝 | 全程使用自己的合法上下文；能闭环通信和恢复，失败可解释；不能借 pane 身份补过关 |
| T12／条件 P0 强边界 | 外部／不可信需求成立时，用第三身份直接读他人 history；降权后重试；从 shell／Node／远程工具尝试读未授权试验 secret | 各真实入口拒绝与允许操作对照、OS／服务端边界 | 所需隔离覆盖实际入口；仅 UI 隐藏或 hook 提示不计通过 |

验收报告将结论标为“通过”“能力反例”“环境受阻”或“未验证”，并为每项结论附可回读证据。

阶段 1 先执行适用的 P0；P1 只随真实插件缺口进入。条件 P0 在对应需求成立时才是准入门槛。失败先诊断配置、调用方式与证据不足，再记录产品缺口；未测场景保留“未验证”。

实际通过只能证明记录中的版本、部署和流程。扩大到另一 host、Harness、浏览器入口或威胁模型时，补验受影响边界。任何 Core 退役另须完成第 6 节迁移门槛。

<a id="archive"></a>

## 9. 历史材料归档与引用

以下 **5 份 Markdown、3 份 HTML 和 3 个完整资料目录** 整体原位归档。所有旧正文中的“已确认”“最终确认”“实施”“验收”、Core 缺口清单、确认顺序以及 P3／P4 Client 计划，均处于原日期的历史语境，不约束当前产品或开发；现行新增要求由本篇承接。

| 历史入口 | 历史用途 |
| --- | --- |
| [UX-DESIGN.zh-CN.md](UX-DESIGN.zh-CN.md) | 旧 Client 页面与交互设计基线 |
| [USER-FLOWS.zh-CN.md](USER-FLOWS.zh-CN.md) | 旧流程、确认记录、能力缺口与实施／验收计划 |
| [PRODUCT-REVIEW.zh-CN.md](PRODUCT-REVIEW.zh-CN.md) ／ [PRODUCT-REVIEW.html](PRODUCT-REVIEW.html) | 旧产品形态复核与候选方案 |
| [COMMUNICATION-EXPERIENCE.zh-CN.md](COMMUNICATION-EXPERIENCE.zh-CN.md) ／ [COMMUNICATION-EXPERIENCE.html](COMMUNICATION-EXPERIENCE.html) | 旧通信、关联阅读研究与呈现候选 |
| [WORKBENCH-ADOPTION.zh-CN.md](WORKBENCH-ADOPTION.zh-CN.md) ／ [WORKBENCH-ADOPTION.html](WORKBENCH-ADOPTION.html) | 前轮工作台采用研究与改造候选 |
| [review-20261105/](review-20261105/) | 完整旧研究、素材、图像与来源 |
| [communication-20261105/](communication-20261105/) | 完整旧通信研究、源码快照、许可、原型与验证记录 |
| [workbench-20261106/](workbench-20261106/) | 完整旧采用研究、Core bridge 可行性、官网观察、媒体采样与源码证据 |

原位归档更新标题与状态封面，历史正文、原路径、URL、相对链接、素材和许可保留。八份入口的原始字节另存[归档快照](orca-first-20261106/archive-audit/original-client-entries.zip)，可按清单哈希核对；快照保存原件，正常阅读使用上表原路径。引用历史事实时注明固定版本、日期、来源与验证范围；新的版本或使用范围须复核。静态官网／媒体观察仍只证明所记录的可见状态，旧原型验证仍只证明其 fixture 行为。

完整范围与保存基线见[归档审计](orca-first-20261106/archive-audit/AUDIT.md)和[364 文件清单及哈希](orca-first-20261106/archive-audit/inventory.json)。本轮能力材料位于 `orca-first-20261106/`，与上述历史资料分开。

Runtime Route的[业务模型记录](../../agent-collabration/routes/collaboration-runtime/design/BUSINESS-MODEL.zh-CN.md)中，Client相关段落另加局部历史注记；该文档其余内容及Core运行合同不属于Client整篇归档范围。

Core／Runtime 的现行独立合同继续由 [UPGRADE-CONTRACT](../runtime/UPGRADE-CONTRACT.md)、[COMMUNICATION](../runtime/COMMUNICATION.md) 与注册 Runtime Route 管理；Client 归档不改变其效力。

## 10. 下一项研究行动

固定可安装 ORCA 版本及源码对应关系，完成原版代表任务和真实插件接入边界试验，形成第 8 节所列证据。优先回答多机状态归属、各 Harness 的原生通信、恢复与身份连续性；存在入口缺口时再验证原生 panel／commands 插件及其合法通信路径。

验收结果用于决定采用原版、插件或进入 Fork 评估，并独立决定 Core 的必要性。本阶段成果是能力验收证据与采用判断。

## 11. 现行实现状态与双向交叉引用

> **现行说明（2026-11-23 · Phase 5 / Phase 6 M5 终版收口）：** 上述第 1–10 节完整保留 2026-11-06 架构研究基线及第 9 节原位归档。桌面客户端工程演进已基于 Orca 上游 Fork 基线落地为 Porpita 桌面客户端（第 94 轮主体集成于 `ab899ffee48ff6263a2422b96e59d24a06c2d436` 完成 **87/87** `--tier all --mode full` 全通，Stage 6B 于隔离工作树 `codex/porpita-ui-spec-91` 经 `0d285b0e5f` 进一步修复非 IPC 局部 mock 下的布局读取回退，终版提交为 `3f30f4d81a6e0da0cbdde74025f0db30baf1d5b6`、tree `9a3e1fb5400fe270f1ad0c0bbd7ef9ec0c76a029`），并与现行 ACS 通信客户端合同（[communication-openapi.yaml](communication-openapi.yaml) · [communication-p1-openapi.yaml](communication-p1-openapi.yaml) · [communication-api-scope.json](communication-api-scope.json) · [communication-contract-adoption.json](communication-contract-adoption.json)，共 35 个操作：`22` 个 `P1_required`、`13` 个 `P2_optional`）及全覆盖 UI SPEC 目录协同治理：
> - 全覆盖总览与规范入口：[porpita-ui-spec/README.md](porpita-ui-spec/README.md)
> - 决策、参考包交付物与 Open Questions #1–#12 对照：[porpita-ui-spec/DECISIONS_AND_SEQUENCE.md](porpita-ui-spec/DECISIONS_AND_SEQUENCE.md)
> - 全覆盖矩阵与回放场景：[porpita-ui-spec/COVERAGE_MATRIX.md](porpita-ui-spec/COVERAGE_MATRIX.md) · [porpita-ui-spec/PLAYBACK_SCENARIOS.md](porpita-ui-spec/PLAYBACK_SCENARIOS.md)
> - 源码基线、诚实边界与结构化设计证据：[porpita-ui-spec/SOURCE_BASELINE.md](porpita-ui-spec/SOURCE_BASELINE.md) · [porpita-ui-spec/COVERAGE_CLOSURE.md](porpita-ui-spec/COVERAGE_CLOSURE.md) · [design-evidence.json](../../.ui-spec/design-evidence.json)

### 11.1 `T01`–`T12` 实机验收基准 ↔ `porpita-ui-spec` 与第 90–94 轮收口映射

| 编号／优先级 | `porpita-ui-spec` 对应目录与旅程 | 现行集成与实机证据状态 | 诚实保留的 `ENV_BOUNDED` 边界 |
| --- | --- | --- | --- |
| `T01`／P0 通信 | `K`、`K.01`–`K.04`、`R.09` · `J05` / `J09` | 第 93 轮已在隔离 PostgreSQL 回环 ACS Core 完成连接、会话、未读与投递状态流实机验证（[第 93 轮](porpita-ui-spec/ITERATION_93.md)） | 真实在线大模型流式问答与跨外网在线会话归属 `EB-01`／`EB-02`（[覆盖边界](porpita-ui-spec/COVERAGE_CLOSURE.md)） |
| `T02`／P0 并行 | `C.10`、`D.07.01`、`D.07.03`、`K.02`、`R.04` / `R.05` / `R.09` · `J04` / `J05` / `J09` | 第 94 轮默认生产构建完成双 Codex 会话分屏、`ResizeHandle` 键盘／Esc 与窄窗聚焦切换实机闭环（[第 94 轮](porpita-ui-spec/ITERATION_94.md)） | 真实双在线 LLM 工具并行执行与额度配额消费归属 `EB-01` |
| `T03`／P0 重连 | `A.05`、`D.07.02`、`D.07.04`、`D.07.05`、`F.04`、`K.01`、`N.general.01`、`R.06` / `R.12`、`S.08` · `J06` / `J12` | 第 93 轮二次重连／`p1_only` 降级同步通过；第 94 轮 `porpita-workspaces.json` v3 冷启动恢复与损坏档案安全降级通过 | 跨两台物理机器网络断开／远端 HTTPS 集群重连归属 `EB-03` |
| `T04`／P0 历史 | `C.10.08`、`K.02`、`K.04`、`R.09`、`S.04` / `S.07` · `J09` | 第 93 轮 `/snapshot` 去重、过期搜索命中清空与未读回执同步在回环 ACS Core 实机闭环 | 跨多物理设备实时历史与远端 SaaS 托管工作流归属 `EB-02` / `EB-03` |
| `T05`／P0 重试 | `E.10`、`K.03`、`K.04`、`R.12`、`S.07` · `J05` / `J09` / `J12` | 第 93 轮 Managed Core `messages.newest` 校验与 `PendingInspectionAction`（`visible` 先于 `pendingFailed`）幂等状态核查通过 | 真实外网长链路并发超时与在线 LLM 发送中断归属 `EB-01` / `EB-03` |
| `T06`／P0 常用会话接续 | `C.10.03`、`C.10.05`、`C.10.06`、`E.01`、`G.06`、`G.06.01`、`N.session-history`、`R.03` · `J03` / `J05` / `J06` | 第 94 轮默认集成左栏 `SidebarSessionIndex` ↔ Vault 双向检索、`Unopened history` 未打开历史续接与回原 Workspace 通过 | 跨物理机器或跨用户真实在线账号历史迁徙归属 `EB-01` / `EB-03` |
| `T07`／P0 基础权限 | `A.03.05`、`A.03.07`、`C.10.09`、`G.09.04`、`K.01`、`M.02.25`–`M.02.36`、`S.06` / `S.08` · `J03` / `J07` / `J11` / `J12` | 同机回环配对、配对代次校验、撤权后界面锁定移除及 Linux X11/Wayland/GNOME 第 66–89 轮证据已归档 | 两台独立物理机异地配对实时撤权专项与远端 Core 部署归属 `EB-03` |
| `T08`／P0 知识接续 | `C.10`、`H.02` · `J08` / `J10` 及完整基线文档链 | `SOURCE_BASELINE.md`、`coverage-audit.json` 与 `source-index` 严格对齐终版提交 `3f30f4d81a6e0da0cbdde74025f0db30baf1d5b6`，M4/M5 建立与 `ORCA-FIRST.zh-CN.md`、11 份参考交付物及 `.ui-spec/design-evidence.json` 双向闭环 | 无额外硬件阻塞；跨机 Git 基线仍须交接核对提交哈希 |
| `T09`／P1 插件入口 | `A.03.02`、`G.08`、`L`、`L.05`、`L.06`、`N.plugins`、`R.10` · `J10` | 第 92 轮修复非打包 `orca-runtime.mjs` 路径解析、禁用开关焦点恢复与 Porpita 安全提示（[第 92 轮](porpita-ui-spec/ITERATION_92.md)） | 第三方在线插件市场实时下载与远端 SaaS 扩展归属 `EB-02` |
| `T10`／P1 插件 API | `F.01`–`F.05`、`G.08`、`L.06`、`N.plugins`、`S.06` · `J05` / `J10` / `J12` | 第 92 轮验证插件 frame 会话隔离（`plugin-frame-guest-sessions`）与停用卸载边界 | 第三方任意外部插件内部权限行为由各提供方按第 10 节边界实测 |
| `T11`／P1 直接通信 adapter | `G.08`、`L.06`、`K.04`、`R.10` · `J09` / `J10` | 规范明确保持 `Native Session` 与 `ACS Conversation` 独立身份（参见 `communication-contract-adoption.json` `NativeSourceLookup`）；禁止绕过身份映射 | 外部未信任直接调用仍按第 2 节条件需求受服务端 ACL 约束 |
| `T12`／条件 P0 强边界 | `C.10.08`、`E.09`、`I.02`、`K.01`、`N.developer-permissions`、`P.06`、`S.06` · `J09` / `J10` / `J12` | 第 90–93 轮覆盖 `SecuritySurface` 信任避让、`add-repo` 受控弹窗回焦与 `p1_only` 作用域边界 | 外部不可信威胁模型下服务端／OS 边界须在目标部署集群独立验真（第 2 节） |

### 11.2 `UX01`–`UX22` 用户体验场景 ↔ `porpita-ui-spec` 双向交叉对照

| 场景编号 | 场景名称 | `porpita-ui-spec` 目录条目与旅程 | 现行状态与待验边界 |
| --- | --- | --- | --- |
| `UX01` | 安装并首次启动 | `A.01`、`A.04`、`B`、`B.01` · `J01` | 第 90 轮完成 Onboarding 品牌/焦点/文案修复（[第 90 轮](porpita-ui-spec/ITERATION_90.md)）；macOS、Linux、Windows ARM64 与正式签名安装升级归 `EB-05` |
| `UX02` | 原生工作台完整 | `A`、`D`、`D.01`–`D.08`、`E`、`F`、`G`、`H`、`I` · `J02` / `J04` / `J08` | 第 92/94 轮默认生产构建集成一体化顶栏、分屏与保留工具且 0 回归 |
| `UX03` | 原生Agent执行体验 | `E.01`–`E.10`、`F.01`–`F.05`、`R.05` · `J05` | Native Chat 界面、Vault 回源与本地合成会话已测；真实登录 LLM 流式与审批执行归 `EB-01` |
| `UX04` | 两个Agent自动接入 | `C.10`、`D.07.01`、`D.07.03`、`K.01` · `J03` / `J04` / `J09` | 第 93 轮回环 ACS 接入 + 第 94 轮双 Codex 分屏已测；双真实在线大模型自动并发归 `EB-01` |
| `UX05` | 真实跨Harness来回通信 | `K`、`K.01`–`K.04`、`R.09` · `J09` | 对应 `T01`/`T02`；第 93 轮隔离 PostgreSQL 回环 ACS Core 实机闭环，真实大模型在线执行归 `EB-01` |
| `UX06` | 无任务通信与最小协作入口 | `C.10.08`、`K.01`–`K.02`、`N.general.01`、`R.09` · `J09` | 第 93 轮标题栏协作 Dialog、术语统一与设置页同步实机闭环 |
| `UX07` | 忙时消息和原生队列 | `E.10`、`K.03`、`K.04`、`S.04` · `J05` / `J09` | 本地排队 UI 与 ACS 投递状态分层就绪；真实在线模型忙时插队流式归 `EB-01` |
| `UX08` | 提问与人类审批 | `E.09`、`K.04`、`O.local.trust`、`S.05` · `J01` / `J05` / `J09` | 第 90/91 轮完成信任交互与受控 `<Dialog open>` 回焦；真实线上工具审批流归 `EB-01` |
| `UX09` | 消息历史/实时/搜索 | `K.02`、`C.10.08` · `J09` | 对应 `T04`；第 93 轮 `CollaborationSearchResults`、`/snapshot` 与未读同步实机闭环 |
| `UX10` | 消息跳到实际执行 | `C.10.02`、`C.10.05`、`K.04`、`R.09` · `J03` / `J05` / `J09` | 按 [communication-contract-adoption.json](communication-contract-adoption.json) `ReadMessageResponse.native_source` 合同与第 93/94 轮定位路径实现；在线运行定位归 `EB-01` |
| `UX11` | 私人阅读与草稿 | `E.04`、`K.02`、`K.03` · `J05` / `J09` | 符合合同 `Draft` revision 0 `updated_at: null` 与 Native Chat 会话级草稿隔离 |
| `UX12` | 文件与图片分享 | `E.05`、`H.03`、`K.03` · `J05` / `J08` / `J09` | 第 93 轮协作附件与 Meta 字节预算合同对齐；真实在线收发归 `EB-01` |
| `UX13` | 可选任务编排仍可用 | `J`、`J.01`–`J.06`、`L.01`–`L.02`、`N.tasks`、`N.orchestration`、`R.09` · `J09` | 第 92 轮 Automations/Tasks UI 收口；真实外部 GitHub/GitLab/Linear/Jira OAuth 账号归 `EB-02`（在线执行归 `EB-01`） |
| `UX14` | Gate与群组语义保留 | `D.08`、`D.08.01`、`D.08.02`、`K.01`、`S.06` · `J03` / `J09` / `J12` | 第 94 轮验证 `General/通用` 内建组防删改与标签组隔离；第 93 轮验证 ACS 项目边界 |
| `UX15` | 退出重开与短暂断开 | `A.05`、`D.07.02`、`D.07.05`、`K.01`、`R.06` / `R.12`、`S.08` · `J06` / `J12` | 对应 `T03`；第 93 轮重连 + 第 94 轮 `porpita-workspaces.json` v3 冷恢复与损坏 JSON 降级闭环 |
| `UX16` | 目标更换与重复提交 | `A.03.05`、`D.07.04`、`K.01`、`K.03`、`S.07` · `J09` / `J12` | 对应 `T05`/`T06`；遵守 `NativeLink` `expected_host_ref` / `expected_provider_generation` 校验与第 93 轮幂等确认 |
| `UX17` | 已有Core服务登录 | `K.01`、`N.general.01` · `J01` / `J09` / `J12` | 第 93 轮隔离 ACS Core 连接/断开/重连实机通过；外网远端 HTTPS/TLS 物理集群归 `EB-03` |
| `UX18` | 品牌和服务出口 | `B.01`、`L.04`、`L.05`、`M.01`、`N.orca-account`、`N.repo` · `J01` / `J10` / `J11` | 第 90/92 轮全量清理 Porpita 品牌文案与 `zh`/`en`/`ja` 词典；跨端发行包出口归 `EB-05` |
| `UX19` | 原生UI与响应体验 | `A.02`、`N.appearance`、`O.modal.*`、`P` (`P.01`–`P.13`)、`Q` (`Q.01`–`Q.05`)、`R.13`、`S`、`T` · `J13` | 第 91/92/94 轮 `158%` 缩放、高对比、减少动效、`600×400` 与键盘焦点全通；OS 前台聚焦与物理读屏归 `EB-04`，硬件语音/WebAuthn 归 `EB-06` |
| `UX20` | 同一候选升级/卸载交付 | `A.05`、`N.general`、`N.servers` · `J01` / `J06` | 第 94 轮源码基线与 Windows 候选 11 交付对照保留；签名安装包实机升级/卸载及跨 OS 平台归 `EB-05` |
| `UX21` | 实际远端Host链路 | `A.03.03`–`A.03.14`、`C.03`、`C.10.09`、`D.07.03`–`D.07.05`、`G.06.01`、`G.09.01`、`M.02.25`–`M.02.37`、`N.servers`、`N.ssh`、`R.11` · `J07` / `J11` / `J12` | 同机双 Runtime 配对与物理 Linux OpenSSH/Wayland/GNOME 第 66–89 轮已取证；物理双机异地网络与真机移动配对归 `EB-03` |
| `UX22` | 最终功能与路径收口 | `R` (`R.01`–`R.13`)、`J01`–`J13` · [覆盖边界](porpita-ui-spec/COVERAGE_CLOSURE.md) · [设计证据](../../.ui-spec/design-evidence.json) | 20 域、371 项条目通过第 90–94 轮与 M4 跨文档收口；6 类 `ENV_BOUNDED` 条目（`EB-01`–`EB-06`）严格保持诚实待验 |
