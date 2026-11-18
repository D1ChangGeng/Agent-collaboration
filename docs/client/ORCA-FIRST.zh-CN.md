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
