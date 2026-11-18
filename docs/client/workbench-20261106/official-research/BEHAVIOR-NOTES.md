# Orca 官网行为观察

观察日期：2026-11-06 JST。来源：[Orca 官网](https://www.onorca.dev/)。这是官网载体和营销演示的视觉调查，不是已安装 Orca 的运行验收。

## 条件和边界

- Windows 原生 Chrome，程序文件版本 157.0.8103.38；agent-desktop 1.1.0。观察对象为公开官网。
- 公开研究窗口：`w-124519318`，页面地址由可访问树确认 `https://www.onorca.dev/`。最后主动触发的hero项目为Chat or terminal。
- 原始 PNG 为 1920×2160，capture scale factor 1.5；浏览器缩放未测量。网站为暗色、英语，产品演示描绘 macOS chrome，不能由此证明 Windows App 的对应行为。
- 全部正式截图前均确认了在线官网来源。
- 28 张实际查看且可解码的截图列在 `VERIFIED-SCREENSHOTS.json`，包含尺寸、字节数、SHA-256、文件时间和实际查看方式。`-crop.png` 为从原图 `(105,700)-(1875,1530)` 提取的细节裁切，仅用于放大检查，原图保留。
- 观察采用有序稀疏截图，工具调用耗时包含抓取开销。不能据此判断自然速度的流畅度、精确延迟、帧率或所有中间状态。
- 官网场景以固定 ACME 项目、模拟光标、固定提示词和自动重复阶段呈现。没有登录、安装 App、提交下载、启用插件、真正运行命令或创建 PR。DOM / SVG / Canvas / 视频的具体实现未在本调查内确定。不能用这些像素证明底层能力。

## 实际操作与空间结构

1. 在线页面初始 hero：左侧按 host → repository → worktree → agent 会话组织。显示 Local Mac、mac-mini，以及不同 repo、工作树名、分支、模型/状态/时间。中央为多 tab 工作区，可同时放 chat、终端、浏览器与文件；右侧有 file explorer；底部有模型用量、资源和 host 数。参见 `00-online-hero.png`。
2. Scroll 到 Agent-first, end to end 区域，查看 12 卡网格。卡片有独立 Inspect 按钮。点击 Orca CLI 后出现大预览 modal：左侧约七成是功能演示，右侧标题/说明/文档链接，下面 01/12 和页点，左右有 Previous/Next，右上有 Close。参见 `01-grid.png`、`02-cli-modal-a.png`。
3. Next 逐页查看 12 个功能；每次均重新取得 live refs。末页后用 Previous 返回 Computer Use，再 Close 返回原页面。页面定位保持在功能网格附近。没有观察到公开的 Play/Pause 控件。
4. Hero 主动点击 Run anywhere，实际像素显示选中该 tab、桌面工作区和手机任务面板并置；双帧先是 `gh pr create --fill` pending，后为演示 PR #418 已创建，手机也显示相应进展。参见 `16-run-anywhere-a/b.png`。这是演示的同步叙事，不证明实际远程会话、SSH 建连或传输恢复。
5. Hero 主动点击 Chat or terminal，实际像素显示左侧结构化 chat、右侧 Claude Code 原生 TUI，同时展示同一拒收 PO box 任务；双帧从 Working/Update running 到摘要和29个测试的完成文本。参见 `17-chat-terminal-a/b.png`。它表达两种视图并置；没有实际切换一个真实会话或验证语义等价。

## 12 个卡片：实际查看的采样状态

下表的“变化”均指官网预设演示像素，不代表我触发了被描绘的产品命令。并非每卡都有完整从起点到终点的连续回放。

| 卡片 | 采样观察 | 证据与缺口 |
|---|---|---|
| Orca CLI | 终端中出现 `orca worktree create --name promo-tests --agent grok --prompt ...` 和 Running；网格态另显示 promo-tests 工作树及 Grok worker | 02/03 + 01；02/03 都处于 Running，不能宣称双帧完整见证 spawn 完成 |
| Split Anything | 网格态为 chat/browser/terminal/diff 组合；modal 采样为 chat 与 terminal 上下分屏，上方存在文件/浏览器 tabs | 01、04；实际拖拽分屏、重排、撤销没有操作 |
| Jump Anywhere | 搜索浮层覆盖工作区，输入入口称可搜索 chats/terminals/workspaces/tasks/settings/actions，列出工作树和 repo 标签，底部显示 Command+J | 05；只查看了预设搜索状态，没有实际搜索真实 host |
| Drag Files to Agents | a 帧为 AddressForm.tsx 在拖动、中央 Drop to attach 提示，明确说以 agent 可读路径加入；b 帧回到 chat 和 composer | 06a/b；中间 attachment token 的全部形成过程未连续捕获 |
| Design Mode | a 帧为浏览器元素选取和 `Continue to payment` selector 标注；b 帧 chat 已有 Selected element 上下文且 Working，浏览器保持旁边 | 07a/b；没有复制真实业务站点 HTML |
| Rich Previews | chat 侧称截图已保存，图片 tab 在右侧；后续帧图片缩放由33%到26% | 08b、09-rich-preview-b；仅 PNG 预览，PDF/Markdown 仅文案，没有实际查看 |
| Mobile Emulator | iPhone17Pro 面板位于 agent 旁；演示命令含 `orca emulator tap/type/ax`；两帧分别显示完成说明和较早 Running 阶段，证明场景会循环复位 | 10a/b；未运行任何真实 iOS/Android emulator |
| Dictation | 一帧已有用户口述任务和 Editing；后帧回到 Command+E、Speaking 浮层及部分转写 | 11a/b；采样跨越循环，不是一次工作倒退；未使用麦克风 |
| Usage & Accounts | 底部模型进度条打开 Grok quota 浮层；另一帧为 Codex session/weekly/reset，两个 account 及 Manage Accounts | 12a/b；真实额度刷新、登录、切号未操作 |
| Automations | Create automation dialog 含 prompt、agent、schedule/time；另一帧 schedule 菜单列 Hourly/Daily/Weekdays/Weekly/Custom cron | 13a/b；没有创建/启停真实自动化，持久化和重启补偿未知 |
| Computer Use | chat 旁描绘外部 Safari；演示出现 `orca computer get-app-state --app Saf...`，输入字段在旁 | 14a/b；两帧均为任务前段，实际输入/成功结论未覆盖 |
| Plugins | All/Installed/Not installed、搜索、Orca Midnight 与 Excalidraw 两张卡，Installed 标记与 toggle；a/b 有模拟 cursor 和视觉状态差异 | 15a/b；没有真实安装。主题/编辑器/语言/panels 是官网说明，API和隔离模型需源码证明 |

## 对 ACS 方案的含义

可见证据支持把 Orca 当作“完整 ADE / 多代理工作台候选”研究：host 与 worktree 导航、多种 agent 视图、pane/tab 组合、相邻工具和产物预览形成同一空间，明显超出单聊天面板。Run anywhere 的演示也描绘了主代理把任务拆给 Codex/Grok，再汇总两 worker 结果后继续工作的产品叙事。这些与 ACS 目标有较大表面重叠，值得让源码/试运行审查回答能否复用真实实现。

官网调查不能证明 ACS 的这些关键契约：稳定联系人和接收地址、跨项目权限、可靠消息投递与明确回复、session/worker/worktree/host 的持久身份关系、断线重连后的历史与请求连续性、通知触发及点击恢复、取消/超时/重复投递、协作编排的授权归属。没有观察到真实通信收件箱或对这些边界的失败恢复测试。

未完成且不应外推的覆盖：hero 的 Review AI output / Git integration / Extend with plugins 未主动逐页检查；没有实际 SSH host 添加/建连/断线重连、真实 agent pane/tab/sidebar 操作、通知到达/点击恢复、App 重启恢复、键盘/触摸/ reduced-motion、响应式和其他主题。官网按钮与静态场景只能给这些进一步检查提供入口。

下一项最有价值的验证是结合源码确定每项场景的真实状态拥有者、持久化／权限／通信边界，再用安装版重现host→worktree→worker→reply→断线恢复的闭环。本调查建立视觉与交互参照；实际产品采用及设计接受另行确认。
