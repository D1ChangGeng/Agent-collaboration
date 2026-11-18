# ACS Client 外部产品研究证据

研究日期：2026-11-05。角色：独立研究；本记录没有选择最终 Client 布局、修改正式 UI SPEC 或实施产品 UI。

## 本次可用证据与限制

- 已实际查看 6 个产品的官方图像：Zulip、Slack、Linear、VS Code、OpenCode、Codex。图像为官方产品示例或帮助图，不是本项目实现。
- 已实际查看两种官方连续媒体的有序帧：Zulip 导航 tour（116.52 秒 MP4，1920×1080，25 fps）与 Slack Activity（21.79 秒 GIF，1460×1000，523 帧，循环）。本次没有自然速度播放判断；有序帧能支持所见状态及顺序，不能证明帧间流畅、真实服务延迟、失败恢复或实际操作。
- **亲自交互尚未完成。** 浏览器连接遇到 request-header policy 加载错误；桌面控制因无法可靠确定当前 URL 被要求停止。产品操作、键盘与失败恢复体验仍缺亲手观察证据。
- 全部观察是英文桌面示例；没有验证中文、窄窗、键盘、草稿恢复、真实权限和大规模数据。部分文档图是裁剪或示意，不应推算实际 pane 宽度。
- 图片/视频只作本次研究引用。**产品参考与可复用实现分开**：截图不提供可重用代码或授权。成熟来源采用仍需版本、许可、技术适配和本地试用。

## 比较结论：有价值的是对象与继续工作的关系

| 机制 | 产品证据 | 对 ACS 的价值 | 主要误用风险 |
|---|---|---|---|
| 按话题整理未读会话 | Zulip | 从待读集合进入具体往来，保留组织上下文；读完与回复分开 | 把 Route 当作所有人可见的公共 channel；直接复制自动已读语义 |
| 按个人注意力聚合活动 | Slack | 同一往来的不同入口；列表密度可切换；已读、清除与持续会话分开 | 把个人 Inbox 扩张成项目全体私信；把 badge 当任务完成 |
| 以持久工作对象为主的通知中心 | Linear | 通知行指向 issue；提醒不等于原对象；适合检验 Inbox 的语义 | ACS 没有 issue/task 领域，不应引入任务状态机作为主导航 |
| 多上下文工作台 | VS Code | 稳定 chrome 中切换视图、并排内容与原生窗口，层次不等于页面 | 每个层次变一列或全量复制 IDE、terminal、原生 trace |
| 会话与执行位置相邻 | OpenCode | 会话内容与 server 连接状态分层，连接设置可局部呈现 | server 绿灯当作联系人可接收或 Agent 空闲；旧截图当当前 v2 |
| 项目组织的并行 Agent thread | Codex | 项目上下文、线程、原生 review/hand off 共存；继续原生执行 | 把 ACS Slot 当单个临时 thread；重做原生 trace、diff 与执行管理 |

**研究建议，非最终设计决定：**“个人 Agent 通信工作台”有比“任务编排台”更强的证据适配。需要修正的是把 Inbox 视为个人获授权的待关注往来集合，而不是把 Root、Route、Slot、Session 都映射成一级页面。联系人是稳定对象；Native Session 是当前可选接收位置；往来详情应能给出相关上下文与原生继续入口。具体常驻区域与导航仍需代表性内容和实际操作验证。

## R1 — Zulip：会话为单位的收件箱

原始来源：[Getting started](https://zulip.com/help/getting-started-with-zulip)、[公开社区入口说明](https://zulip.com/help/trying-out-zulip)、[公开社区](https://chat.zulip.org/?show_try_zulip_modal=)。无需创建账户的社区是发现的交互候选，本次未操作。

证据：

- [官方 channel/topic 关系图](zulip-channels-topics.webp)，原图 <https://zulip.com/help/_astro/channels-and-topics.q25zXrY7_1B49P2.webp>，已查看。
- [官方 tour 原片](zulip-navigation-official.mp4)，原片 <https://static.zulipchat.com/static/navigation-tour-video/zulip-10.mp4>，由官方 help 直接链接；文件已解码并查看以下有序帧。
- [全片定位表](zulip-tour-contact-sheet.jpg)、[26–50s 阅读/继续/返回片段](zulip-tour-reading-episode.jpg)，均已查看。保存单帧 `zulip-tour-030.00s.jpg`、`032.00s`、`042.00s`、`044.00s`、`046.00s` 等。

实际看到：10–30s Inbox 以 channel 分组，topic 为子行，右侧对齐未读计数。30s 指针定位 moving to Zulip；32s 消息面板呈现同话题；38–40s 底部为折叠的 Message 入口；42s composer 展开，channel 与 topic 明示在输入上方；44s 新回复出现在同一话题消息流；46s 回到 Inbox，原话题已不在未读列表，general 未读从 6 降到 3。50–70s 演示从 channel 起新 topic，composer 同时承担命名与正文，后续成为侧栏中的 topic。视频有放大、字幕和剪辑，部分操作跨度没有逐帧检查。

视觉关系：窄的组织树和对齐计数承担扫描，消息正文使用大块阅读区域；topic 标题条把组织位置与正在阅读的对象连在一起。折叠输入入口使“先读”成为独立有效状态；展开后目的地不会从视野中消失。

ACS 启示：跨次返回应恢复“与谁、在哪个项目/Route、回复哪条原消息”；读消息与产生 reply 应是不同操作。Route 可以作为上下文/过滤条件，不能据公开 channel 的视觉模型推断 ACS 的消息可见性。

不适用：Zulip 的 channel 发布、群体订阅、自动已读/消失和命名 topic 不能直接迁移。ACS 的 Inbox/read 不消费消息，外部 Agent 主动 reply 才建立回复关系，且 invoke 可能把文本交给 Native Session 执行。

复用边界：Zulip 是可研究的成熟开源产品；本次未取得或评估前端代码，不能把帮助图当已采用的实现。

## R2 — Slack：个人 Activity 与消息原上下文

原始来源：[Activity](https://slack.com/help/articles/19693583638803-Get-your-work-done-from-the-Activity-view)、[新 Activity 说明](https://slack.com/intl/en-gb/help/articles/46751260742035-Introducing-the-new-Activity-view-in-Slack)、[Threads](https://slack.com/help/articles/115000769927-Use-threads-to-organise-discussions-Use-threads-to-organize-discussions-)、[官方交互 tour](https://slackdemo.com/?from=home)。tour 已发现，本次未操作。

证据：

- [官方 thread 帮助图](slack-thread-official.png)，原图 <https://slack.zendesk.com/hc/article_attachments/32816788692243>，已查看。图为抽象化帮助示意，部分内容画成灰线，不是完整 production screenshot。
- [官方 Activity GIF](slack-activity-official.gif)，原件 <https://slack.zendesk.com/hc/article_attachments/48378858456851>；新 Activity 说明页另一个附件 `48480228262419` 的下载字节相同。保留 [时序定位表](slack-activity-contact-sheet.jpg)，已查看。

实际看到 GIF：3.96s 显示 Activity 卡片列表；5.96s 打开创建视图 modal；8s 视图名称/通知类型处于配置；10s modal 关闭，My view 成为顶部 tab；12s 指向布局按钮；14s 同一列表已切成紧凑行；16s 选择两行后出现 `Mark as Read` 与 `Clear` 两个动作；18s 三项选中并指向 Clear；20s 选中行消失，剩余条目保留；21.67s 为紫色尾帧。GIF 是带示意文字和庆祝效果的官方讲解，不能证明真实服务结果。

文档声明：已读只改变阅读状态，不从 Activity 隐藏；清除会隐藏并保留 Cleared 入口；新回复仍会出现。消息可从 Activity 直接回复，也能返回 channel/DM。新旧 Activity 正在渐进 rollout，不能将该 GIF 泛化到所有当前用户。

视觉关系：稳定左 rail、顶层过滤 tab 和列表视图，使“从哪一种集合进入”与“消息本身在哪”分开；密度变化保持对象身份。thread 帮助图把原消息留在 channel 中，右侧重复原消息并呈现 replies，同时保留 channel 位置和关闭入口。

ACS 启示：同一条获授权消息可以有 Inbox、联系人往来、历史等不同入口，避免复制成彼此独立的数据。若 Client 设计待关注/隐藏，应与 Core 原消息保留、主动回复、Native 投递状态分离。全局 Inbox 应明确“我的获授权来信”；不能因 Client trusted 就展示第三方私信。

不适用：Slack 普通发送与 ACS invoke 的作用不同。ACS 发送可能唤起/输入 Native Session；不能把 Slack 风格无说明的 send 箭头当作纯留言默认。Slack 的 channel/多人 thread 权限也不能作为 ACS 可见性合同。

复用边界：Slack 是参考产品，本次无可复用 UI 源码授权。其截图/GIF 只作研究引用。

## R3 — Linear：事件 Inbox 附着于持久 issue

原始来源：[Inbox](https://linear.app/docs/inbox)、[Start Guide](https://linear.app/docs/start-guide)、[官方 demo workspace](https://linear.app/demo)。官方 start guide 明确将 demo 用于注册前学习布局；本次未操作。

证据：[官方 Inbox 图](linear-inbox-official.png)，原图 <https://webassets.linear.app/images/ornj730p/production/b442b340278740de70919c868dce1afca4335fe7-3600x2080.png>，已查看。它是暗色局部裁剪，不能说明全产品 shell 或 pane 比例。

实际看到：Priority/Other 两个带数量的 tab；每行同时有 issue ID/标题、谁做了什么、相对时间、事件头像与 issue 状态图标。例如 assign、comment mention、project update overdue 并非统一的“新聊天”。主体的通知类型与右侧 issue 状态同时存在。

文档声明：Inbox 是订阅 issue 的更新中心；打开条目进入专门 Inbox issue view，并能修改 issue；snooze 隐藏通知至指定时间，reminder 不隐藏 issue。此行为未实操。

ACS 启示：Inbox 行应说清“发生了什么、涉及谁、为何需要看”，并保留原消息/往来入口；消息投递与对方 explicit reply 应分开呈现。它也提供反例：当对象是 issue 时，通知和 task 状态合理共存；ACS 主对象是联系人与消息，照搬 issue 状态会扭曲产品。

不适用：issue、assignee、priority、workflow、cycle 等不应成为 ACS Core 虚构能力。不要用 completed/read 把对方任务完成或回复完成混为一谈。

复用边界：Linear 为参考产品；本次没有可用页面实现或设计系统许可，未采用代码。

## R4 — VS Code：一套稳定 chrome，多对象、多视图、多窗口

原始来源：[User interface](https://code.visualstudio.com/docs/editing/getting-started/userinterface)、[Multi-root workspaces](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces)。

证据：[官方全局布局](vscode-ui-official.png)、[并排编辑](vscode-side-by-side-official.png)、[浮动 editor](vscode-floating-editor-official.png)，三图均已取得并实际查看；不将静态图当操作。原件依次为：

- <https://code.visualstudio.com/assets/docs/editing/userinterface/hero.png>
- <https://code.visualstudio.com/assets/docs/editing/userinterface/sidebyside.png>
- <https://code.visualstudio.com/assets/docs/editing/userinterface/floating-editor.png>

实际看到：Activity Bar 选择工具族，Explorer 树提供当前位置；同一个 workspace 内两个 editor groups 并排，底部 terminal 不占用独立路由。浮动 editor 图里 CSV 从主窗口分离，主 notebook 和 Explorer 仍在原窗口，浮窗有自己的文件身份。

文档声明：重启恢复 folder/layout/open files；editor group 可移动；窗口/视图可浮动。未实操恢复、拖动或键盘切换。

ACS 启示：Root→Route→Slot→Session 的领域层次不要求同样深的页面层次。全局项目选择、局部 Route 过滤、联系人详情、Native handoff 可以是不同粒度；某个对象常驻或弹出应从“是否需要同时比较/继续”决定。不要默认所有层都永久占一列。

不适用：文件系统树、完整 terminal/editor 和 IDE action rail 没有自动成为 ACS 主要工作对象。Native trace/diff 已在原生工具中时，ACS 保留关联和继续入口即可成为合理候选，仍需验证往返连续性。

复用边界：VS Code 项目源代码可作为成熟来源线索；本次只观察官方文档图，未验证源码级适配或许可细节，也未采用 workbench。

## R5 — OpenCode：会话内容与 server 连接分层

原始来源：[Web v1 文档](https://opencode.ai/docs/web/)、[当前 v2 文档](https://dev.opencode.ai/v2/docs)、[官方 repo issue #48342](https://github.com/anomalyco/opencode/issues/48342)、[issue #58101](https://github.com/anomalyco/opencode/issues/58101)。后两项是用户报告，不能当独立运行验证。

证据：[New session](opencode-new-session-official.png)、[Active session](opencode-active-session-official.png)、[Servers modal](opencode-servers-official.png)，均已查看。原图：

- <https://opencode.ai/docs/_astro/web-homepage-new-session.BB1mEdgo_Z1AT1v3.png>
- <https://opencode.ai/docs/_astro/web-homepage-active-session.BbK4Ph6e_Z1O7nO1.png>
- <https://opencode.ai/docs/_astro/web-homepage-see-servers.BpCOef2l_ZB0rJd.png>

实际看到：New session 在输入上方显示工作目录、branch 与最近修改；顶部 server/MCP 状态在内容区外。Active session 在左侧保持消息/可折叠步骤，右侧 Review 显示 session changes。Server 选择是叠在会话上的 modal，底层 composer/目录上下文仍可辨认。

版本局限：这些图来自仍公开的 v1 文档。2026-09 的公开 issue 报告 v2 把 sessions 放到 titlebar tabs、项目与历史回到 home，且有用户请求恢复 sidebar；2026-10 的 2.1.2 报告同样现象。**本次没有实际查看 v2 可操作界面；不能将 v1 图片称作最新 OpenCode。** 这些异议用于提醒导航可达性有权衡，不证明某种布局一定更好。

ACS 启示：运行位置可以用局部状态与选择器表达，不必与稳定联系人混在一份树中。目录、server online、session 内容与 Agent 是否可接收是不同事实。多窗口候选应验证“跨联系人的未完往来能否迅速找回”，不能只看当前 prompt 的简洁程度。

不适用：ACS 不需要重建 OpenCode 的模型选择、token/步骤、diff、工具过程；server 绿点不能推出 Native Session ready 或 Agent idle。

复用边界：[官网](https://opencode.ai/)声明 MIT 开源并链接 repo；本次没有取得特定 commit 或做本地 UI trial，不能把图当已采用实现。

## R6 — Codex：项目上下文、独立 thread 与原生继续

原始来源：[官方 changelog](https://learn.chatgpt.com/docs/changelog)、[Projects and chats](https://learn.chatgpt.com/docs/projects)。旧 `/codex/app/features` 当前重定向到新版 Features；不能用旧页名称断言当前功能布局。

证据：[官方 Windows 图](codex-windows-20260304-official.webp)，原图 <https://learn.chatgpt.com/images/codex/windows/codex-windows-light.webp>；[官方 basic 图](codex-app-20260202-official.webp)，原图 <https://learn.chatgpt.com/images/codex/app/codex-app-basic-light.webp>，均已查看。

日期注意：文件名的日期是 changelog 所关联发布段，不是图片 bytes 的版本证明。basic 图中当前显示 GPT-5.4、Plugins 等内容，说明图片资源可能随网站更新。准确说法是“2026-11-05 取得的官方页面关联示例图”，不能宣称复现某个历史 build。

实际看到：Windows 图的左侧把项目与其 thread 归组，另有置顶/最近往来及 awaiting approval 状态；右侧主区保留连续对话、执行记录、最终回复和 changed-file 摘要，顶部 Open/Hand off/Commit 为独立原生动作。basic 图在空聊天仍将 project、Work locally、branch 与输入相邻，默认权限可见。

当前文档声明：project 保持共享 files/instructions/sources，多 chat 各自保留 transcript；CLI、IDE、desktop 对 project 入口有不同边界；查找、pin/archive 是组织方式，不改变 sandbox 的权限。未实操 thread 互切、原生打开、handoff 或权限提示。

ACS 启示：借鉴“组织上下文与当前独立往来并存”，避免把临时 Native thread ID当稳定 Slot 联系人。Native continuation 应关联准确接收位置并把继续工作的责任交给原生界面。投递已接收、Session 已唤起、出现 explicit reply、实际工作完成应保留各自证据。

不适用：Codex 自身拥有 Agent 执行和产物管理，ACS Client 不是因此就必须拥有相同 trace/diff/review/模型设置；不能把其项目文件权限当 Root 通信命名空间权限。

复用边界：这些是 OpenAI 官方产品参考图，本次没有 Desktop UI 源码或再分发许可判断，不是可复用壳层。

## 会改变下一轮决定的高影响问题

1. **个人 Inbox 的主对象是什么？** 逐消息、原消息+首个 explicit reply，还是按联系人聚合往来？需要用 ACS 真实匿名化样本比较；禁止以聚合 UI 擅自扩大权限。
2. **起点是收件箱还是联系人？** 当没有来信时，新建往来与已有联系人找回是否比 Inbox 更重要？需要首次进入/回归使用场景，不应从参考产品默认首页推断。
3. **发送的实际含义如何在决定点呈现？** ACS 默认为 invoke+async，message_only 是只留言。需验证一个目标 Session 不可达/unknown、已有工作运行、Native 输入被接收却没有 reply 的过程；不能把 wait timeout 当失败重发。
4. **Route 在何处最有帮助？** 是联系人过滤、往来上下文、项目内组织还是单独管理页？用跨 Route 联系同一 Slot 的样本检验；不要把 hierarchy 自动变成导航层级。
5. **打开原生与返回通信的连续性。** 应保留联系人、原消息、reply 关系、阅读位置和草稿；现有静态媒体未证明这一点。
6. **读、待关注、清除的本地语义。** Core 读取不消费 Inbox/history；如果 Client 增加个人处理状态，需明确其持久化和权限责任，不能伪称现有 Core 已有 Slack 式 unread/clear。

## 来源采用与材料管理

所有本次图像均已保留原 bytes，未重画为产品 UI。帧文件来自媒体解码；contact sheet 是研究定位表，不能当界面的实际 viewport。截图/GIF/视频不提供可复用代码。实际采用成熟实现时仍需按具体责任寻找来源并验证 rights/compatibility；本记录只支持产品模型研究与目标结构示意。

