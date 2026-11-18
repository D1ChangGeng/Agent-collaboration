# 用户录屏与截图：Orca 工作台时序证据

研究范围：用户提供的两段本地官网录屏、三张官网截图。用途是判断完整工作台的体验价值及 ACS 增量的边界；没有改产品代码或正式 UI SPEC，没有操作 GUI。

## 结论及证据边界

Orca 在这些资料中呈现为完整开发工作台：左侧按主机、项目、工作树及会话组织工作，右侧可并置 chat、CLI、终端、浏览器、文件、diff、Git 与笔记。最有价值的关系是让任务、上下文、检查和反馈在这些区域之间连续流动。因此，若用户希望保留大部分工作台能力，复用完整成熟实现是比抽取聊天外壳更贴合当前意图的研究方向。

所有下述“动作”“触发”“结果”均指**官网构造的宣传演示中描绘的动作与状态**。录屏里可观察的用户行为是官网内容的浏览与标签选择；没有用户实际操作已安装 Orca App 的证据。网站动画里出现 Started worker、测试通过、PR、Sent、Working 等文字，只能证明这些状态被呈现，不能验证底层程序完成了相应工作。

本次实际查看了全片每 8 秒左右的有序全帧、重点片段每 1–2 秒的有序帧，并打开重要原尺寸全帧。共精选 25 个代表状态，见 [精选清单](curated-frames.json) 和三张联系表：[1](curated/curated_sheet_1.jpg)、[2](curated/curated_sheet_2.jpg)、[3](curated/curated_sheet_3.jpg)。持久归档保留精选全帧、片段联系表和提取时间清单；完整提取帧可从原视频与脚本重现。没有自然速度连续播放能力的实际观察，因此不作流畅度、真实延迟或帧率性能结论。帧时间是 OpenCV seek 请求的秒数，未独立解码逐帧 PTS；短于采样间隔的变化可能遗漏。

## 原件与元数据

原视频保留原路径，没有复制进本目录或仓库。完整数据见 [metadata.json](metadata.json)。

| ID | 原文件 | 字节 | 时长 / 帧数 | 尺寸 / 编码帧率 | SHA-256 |
|---|---|---:|---|---|---|
| V1 | `D:\D26FO\Videos\屏幕录制\屏幕录制 2026-11-06 061639.mp4` | 108160027 | 96.7667s / 2903 | 1796×1172 / 30fps | `c879c9e7cab2091bfc59558d6fb8308f279df0dd474395fcf1314f4718f98851` |
| V2 | `D:\D26FO\Videos\屏幕录制\屏幕录制 2026-11-06 062022.mp4` | 142394400 | 157.8000s / 4734 | 1772×950 / 30fps | `00b522f159eef4fac3e7f491156b9e34c8b219c1df6cb18c733b2edbacd1607f` |

解码器为 OpenCV；`metadata.json` 记录版本。30fps 是录屏文件属性，不是被展示应用的渲染性能。录屏已是官网内容区域，未发现需要保留的其他私人桌面区域；导出保持 whole frame。截图原件复制为 `source-screenshot-1.png` 至 `source-screenshot-3.png`，其源路径、尺寸与 SHA 见 [screenshot-metadata.json](screenshot-metadata.json)。

## 全片分段覆盖

这是抽帧定位范围，边界方括号表示相邻已见帧之间的切换区间，不声称准确切换时刻。

| 录屏 | 已见内容及范围 |
|---|---|
| V1 | 0–24s Orchestrate agents，含不同工作树会话与终端/文件；[24,32] 进入 Chat or terminal；32s CLI；39–50s Review AI output；[50,52] 进入 Git integration；52–72s Git/PR反馈；[72,74] 进入 Plugins；74–86s 插件及主题/语法展示；[86,88] 进入 Run anywhere；88–96.57s 手机与桌面同任务画面。 |
| V2 | 0–8s Workspaces；16–24s Orchestration；28s Chat or terminal 空舞台过渡，30–48s chat/CLI 往返；50s Remote 空舞台过渡，51.5–63.5s 选择主机并建工作树；65s Browser 空舞台过渡，66–82s 浏览器选元素与agent操作；88–96s Terminal；104–112s Tasks；120–126s Editor；127s Notes 空舞台过渡，128–138s 行级笔记；144–157.6s Git integration。 |

V2 切换功能标签时，若干帧先出现短暂空的演示舞台，随后载入对应片段。这是官网演示容器变化，不应归因于 Orca App 页面加载、闪烁或状态丢失。部分片段会重置循环，如 V2 42s 已回到 chat 后，44–48s 又展示上一组起始历史及菜单；不可把重置当作App撤销或消息回滚。

## 决策最有价值的连续片段

以下每一行都只描述**宣传演示所描绘的交互**。原尺寸精选帧以 F 编号定位，另有 `episode-*` 目录的时序联系表。

| 片段 / 时间 | 触发前 → 触发 → 变化 → 稳定/退出 | 证据与观察限度 |
|---|---|---|
| 协调与回报，V1 0–12s | 主会话已有“拆给 Codex 和 Grok”的任务；1s 显示运行协调命令；2s 出现两个 Started worker 条目；4s 右侧上下出现 tax-rules / promo-tests，分别携 Task from coordinator；主会话同时改 changelog；9–10s tax-rules 显示完成并回报，主会话新增 Update from worker；12s 另一个仍在测试。 | F01–F03；[序列](episode-orchestration/v1_sheet_1.jpg)。显示了分工、并行与回报的关系，未看到稳定身份、重连、投递确认或失败恢复。两工作者的最终汇总在 V1 88s 的另一个宣传片段出现，不能作为这段的连续实时执行证明。 |
| chat ↔ CLI，V2 30–42s | chat 已有修改和测试历史；34s 菜单高亮 Continue with Terminal Agent；36–38s 同名 tax-rules 的 CLI 显示先前历史与继续跑测试；40s 菜单高亮 Continue in Chat UI；42s chat 显示测试结果。 | F15–F18；[序列](episode-chat-terminal/v2_sheet_1.jpg)。这是有意义的双向继续叙事；未验证原始CLI进程、会话ID或上下文持久化。44–48s 的重复是演示重置。菜单另有 Hand Off to Another Agent / Fork Agent Session，未在此段实际演示结果。 |
| 浏览器批注 → agent，V1 39–50s | chat与浏览器并置；40s 进入反馈模式；41s 选 ZIP / Postal 字段并开输入框；42–43s 输入国家切换邮编校验反馈；44s 出现一个annotation；45s Send notes to 可选原会话或新 Claude/Codex，含 Include page details；47–48s chat出现带URL、元素、selector与反馈的结构化消息；49–50s 显示读取和编辑文件。 | F06–F09；[序列](episode-browser/v1_sheet_1.jpg)。输入、元素和上下文被保留在反馈路径中；未验证DOM获取权限、真正投递或代码修改结果。 |
| 浏览器元素复制 → agent验证，V2 66–82s | 初始是并置chat与网页；68s 元素高亮；70s Copied；72s composer带浏览器上下文；74s 送入chat；76s 读改文件；78s 显示选择Canada、填写邮编；80–82s 网页呈现Canada与加拿大邮编，chat报告接受。 | [序列](episode-browser-copy/v2_sheet_1.jpg)。与 V1 批注是两种不同路径，不要合并为一个按钮；也不把宣传中的 Ran orca ... 当实际工具执行证据。 |
| Git / PR / 审阅反馈，V1 52–72s | diff旁的 Git 区域从未暂存到已暂存；56s 出现commit消息；58s 显示committed；60s PR草稿及 Push & Create PR；62s 出现#417；64s 显示checks和review comment；66s 反馈进入队列；68–72s 新的 Address review on #417 会话携选中反馈，显示读改文件与测试。 | F10–F12；[序列](episode-git-review/v1_sheet_1.jpg)。这条“检视结果→指派修复”的回路对工作台价值很关键。没有真实Git远端、CI或PR变更验证。 |
| 主机与工作树，V2 51.5–63.5s | Create worktree 中可选 Project、Run on、Create from和Agent；53–54.5s Run on显示Local Mac、mac-mini、build-box、Per-Workspace Environment、Add host；56s选build-box；57.5s出现该主机下的新工作树；59–62s显示新任务运行与读改文件；63.5s重置回创建对话框。 | F19–F20；[序列](episode-remote/v2_sheet_1.jpg)。主机是执行位置，不能从画面等同于ACS Route或稳定Agent。官网旁文称休眠后继续运行，录屏未测试此行为。 |
| diff行级note → agent，V2 128–138s | diff行27；129s开 Add note；130–131s输入拒绝express PO box的反馈；132s形成行级note；134s Send notes to菜单；135s右侧会话显示file/line/comment；136–138s回应该改哪里并显示读改文件，note标sent。 | F24–F25；[序列](episode-notes/v2_sheet_1.jpg)。比复制整段diff更精确的上下文回送关系已被描绘；未验证行锚随后续diff变更的可靠性。 |
| 手机继续任务，V1 88–96s | 桌面展示两worker汇总；88s手机端先显示工作树列表；90s进入同一任务并输入 Ship it. Open the PR；92s桌面与手机都出现输入及working；94s展示gh命令；96s两端呈现Opened #418 / CI running。 | F14；[序列](episode-phone/v1_sheet_1.jpg)。可观察的是跨端同步叙事；没有实际网络、后台执行、鉴权或一致性验证。 |

## whole frame 与视觉关系

- V1 的左侧项目树约占应用宽度五分之一；主任务区可以从单会话切为主会话加两个worker、chat加terminal/files、chat加browser、diff加Git/agent。左侧所选对象与顶端tab共同保持任务定位。宽度是录屏像素的视觉关系，非已测CSS值。
- 黑灰表面、细边界和紧凑tab提供连续框架；黄色工作中标记、provider图标、绿色完成/变更与红色删除给密集内容少量语义强调。浏览器展示的白色网页会成为最亮区域，但左侧chat和项目树仍在原位。
- 每个会话保留自己的composer、model和权限控件；多个agent并置时不会合并成一个模糊输入。worker卡片携父任务入口，主会话收到worker更新，形成可追溯关系。
- V2 的左侧宣传文案和上方功能标签属于官网；它们不属于被展示的App导航。宣传片外框和手机叠层也不能作为App实际空间分配规则。

## 三张截图补充的能力库存

这些只建立“官网展示/声称有此功能”的事实；静态截图不建立其行为。

| 截图 | 可见内容 |
|---|---|
| [S1](source-screenshot-1.png) | Orca CLI；Split Anything（agent、browser、terminal、diff并置）；Jump Anywhere（跨repo/host搜workspace/tab）；Drag Files to Agents；Design Mode（元素HTML/styles/selector送chat）；Rich Previews（images/PDF/Markdown邻近agent）。 |
| [S2](source-screenshot-2.png) | Mobile Emulator；Dictation；Usage & Accounts；Automations；Computer Use；Plugins。Automation图处于半透明叠加过渡，不能从该帧推断稳定对话框布局。 |
| [S3](source-screenshot-3.png) | 官网Orca CLI放大查看modal，右侧说明、docs入口、关闭、前后项和01/12分页；左侧终端描绘创建worker命令。它是官网资源查看器，不是App的独立工作台页。 |

## 对下一步源码/适配核查的影响

用户希望保留工作台的大多数特性；这份证据支持把整套工作台作为候选复用范围，保住上述连续关系，而非先决定删到聊天/收件箱。源代码是否可获得、许可、当前版本与宣传的一致程度，均需由源码核查分别建立，录屏不给出可复用实现。

ACS 应核查的是：现有 Project/worktree/host/session 在实现中由谁持有；稳定Agent联系人、Project/Route身份及跨会话消息可以在何处增量接入；现有 Send notes / Handoff / worker update 是否有可复用适配边界。画面中的同名agent、worker tab、远程host和Run anywhere都没有证明ACS所需的稳定联系人、Route独立生命周期、可靠投递或恢复语义。

采用前的高影响未决项：完整UI source与许可；录屏是否代表当前可运行版本；worktree/host/Project与ACS身份的映射；模型与CLI的继续会话契约；投递失败、重启、离线、取消、快速重复输入的真实反馈；插件API边界。相关运行验证应在可操作真实候选中完成。

所有文件都是研究证据；未声明资源已采用、产品已连接或UI已获接受。
