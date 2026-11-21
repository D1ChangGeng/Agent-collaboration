# 覆盖边界与待补证据

覆盖矩阵记录 20 个域、371 个条目。M.04.02–M.04.07 已完成并获确认；第 90 轮完成 F01/F02 桌面局部修复；第 91 轮完成 **F03**（`P`、`P.01`–`P.03`、`P.06`、`P.07`、`P.10`、`P.12`、`P.13`、`Q`、`Q.01`、`Q.04`、`Q.05` 与 `N.appearance`）及受控 `<Dialog open>` 回焦修复（`O.modal.add-repo`）的局部实现与实机核对。 [第 89 轮](ITERATION_89.md) · [第 90 轮](ITERATION_90.md) · [第 91 轮](ITERATION_91.md) · [矩阵](COVERAGE_MATRIX.md) · [核对报告](coverage-audit.json)

需要真实权限、工具或设备的条件继续保持待验。比如未登录 Chat 不能验证流式或实际审批，未配置 Core 不能验证在线状态与历史恢复，一台 Windows 机器不能验证 macOS/Linux 原生窗口或两台机器的作用域边界。用隔离环境和受控账号完成这些场景后，再据 [回放](PLAYBACK_SCENARIOS.md) 更新对应行；保留项也走相同验收。

| 责任 | 已得到的证据 | 关闭前还需要什么 |
| --- | --- | --- |
| 入口与机制 | 9 个 Active View、37 个 Settings 目标、37 个根挂载边界、32 个基础组件封装已绑定到目录；另查侧栏条件入口、独立窗口、工作树内容视图和原生窗口调用 | 从各条件/布局实际触发，核对深链接、菜单和边界之外的手写控件。首轮 91 个未归属候选已映射；目录队列中的叶级覆盖仍按功能域追踪 |
| 现有产品 | Windows 候选 11 与当前 HEAD 隔离构建的真实界面；浅深、常规/窄窗、减少动态终点、Dock 开合采样；安装版设置 32 个常规分区与 1 个动态项目分区首屏 | 在三平台补齐未测路径；执行 N.setup-guide、N.linear、N.dev、N.developer-permissions 等条件入口；项目设置已观察 Git 首屏，其余 scope 与每个设置子状态继续待测 |
| 本地工作台 | 文件树、Markdown、Git Changes/Diff、现有终端分屏、Browser 空白、工作区看板、Codex 原生 Chat 未登录、任务/协作入口 | 原生流式/工具/批准执行、Git 写操作/托管审阅、专用文件视图和实际存盘回归；历史和组件预览可辅助定位证据，不自动提升本轮通过范围 |
| 目标组织模型 | Windows 预览包含标题栏组和档案恢复、目录与 Vault、未打开历史续接、真实会话状态流、跨 Runtime Workspace 与固定 Explorer | 补齐跨物理设备的 Workspace 和 Explorer、ACS 消息到原生会话的授权关联、登录后执行、系统读屏与其他平台 |
| 业务、平台与可访问性 | 安装版已有历史工作台和协作证据，当前有无连接/空态及焦点相关观察 | 目标集成后重跑 J01–J13。用受控 Harness/Core/SSH/WSL、受控任务账号和插件验证；macOS/Linux 原生窗口、键盘/读屏、语言与视觉回归按实际条件补齐 |

| 运行条件 | 需要的环境和可判定结果 |
| --- | --- |
| Space 分支复核 | Windows 本机已验证部分完成、分支变化、另一个工作树占用、释放后重试和保留分支。使用两个可单独重连的 Host，核对同名分支范围、拒绝消息传递及异机恢复。原生前台、读屏与其他平台分别测量。 [回放](evidence/README.md#第-5153-轮) |
| 分支占用的工作树定位 | Windows 隐藏窗口回放覆盖应用登记和外部 Git checkout，核对路径、主窗口活动工作树及返回复核。多 Host 同路径、WSL 路径映射、原生窗口前后台切换与系统读屏分别待实测。 [回放](evidence/README.md#第-5456-轮) |
| 主工作台返回 Space | Windows 隐藏窗口验证状态栏入口、原控件焦点和勾选，以及取消、提交、重载和关闭后的入口回收。移动实际 Git 工作树后，原按钮移除时的回退也已覆盖。系统前台切换、读屏和其他平台待验。 [第 57–59 轮](evidence/README.md#第-5759-轮) · [第 60–62 轮](evidence/README.md#第-6062-轮) |
| Space 提交前核对检出 | Windows 本机以真实 Git 验证移动、解除占用、HEAD 变化、引用暂不可读和再次占用。系统读屏待验。 [第 63–65 轮](evidence/README.md#第-6365-轮) |
| 配对主机与 WSL 检出复核 | 回环配对用于已连接、手动断开和同一配对恢复。Windows 本机使用 Ubuntu WSL 文件系统和 Linux Git。停止恢复与独立 SSH 的后续证据见下行。 [配对主机](ITERATION_66.md) · [WSL](ITERATION_68.md) |
| 连接恢复与独立 SSH 接入 | Windows 和物理 Linux 实测同版本配对、项目接管、原行恢复及 Git 拒绝后的显式重试。Ubuntu 的隔离 X11、Wayland Sway 及 GNOME Shell 各有键盘与 GNOME Orca 回放。自定义系统键、其他合成器、其他语言及配对 WSL 服务按各自条件验收。 [GNOME 证据](evidence/README.md#第-8183-轮) · [X11 证据](evidence/README.md#第-7577-轮) · [Sway 证据](evidence/README.md#第-7880-轮) · [WSL 证据](evidence/README.md#第-6971-轮) |
| 窄窗 SSH 目标辨识 | GNOME 720px 平铺已实测同前缀 IPv4 手动条目，以及从配置导入的 IPv6 条目。后者验证继承用户名、首次密钥取消和确认、随后重连及 Orca 完整身份播报。更大列表、跳板和其他平台读屏按各自条件验收。 [IPv4](evidence/README.md#第-8486-轮) · [IPv6 和首次确认](evidence/README.md#第-8789-轮) |
| 跨 Host 工作空间 | 同机两个隔离 Runtime 已用于核对会话组合和客户端重启。下一层用两台可独立断开和恢复的物理设备，验证实际网络条件、授权在线撤回及输入写入所属 Host。原生 ID 或工作树身份碰撞先明确草稿和文件路由的归属。 |
| Standalone / Embedded SidePanel | 固定 Explorer 预览支持本机和配对 Runtime 的同名路径。目录、筛选、选中项与位置可恢复，滚动按本次预览的同一目录与筛选保持。完整文件树、Contents、同窗多个嵌入工具、分页边界和原生读屏继续按 G.09/J07。 |
| 状态栏的 Host 范围 | 预览的用量与端口按各自的工作对象确定，资源汇总明确为本机，项目树保留来源。实际登录、换账号及真实额度、双物理 Host 相同端口号、原生采样及转发仍按条件验证。 |
| 端口与资源回源 | 本机端口在应用内 Browser 的打开及监听替换已用真实环回服务验证。配对 Host 的详情与原工作台入口可用。资源表定位使用已归属样本并验证了真实导航。配对浏览器、前台采样与跨设备转发保留各自的验收环境。 |
| 本机 PTY 与 Space | Windows 英语和简中已验证批量三态、目录图返回焦点、筛选隐藏项保留和单项删除审阅后取消。前台系统焦点、采样与其他平台继续按实际环境验收。 [简中 PTY](evidence/iteration-42-44-resource-selection-zh/i42-pty-eligible-selection.png) · [简中 Space](evidence/iteration-42-44-resource-selection-zh/i44-space-filtered.jpg) |
| Space 确认与结果 | 隐藏 Windows 客户端用真实临时工作树验证取消、单项清理、部分拒绝和重试。主窗口同步后失败保留在原行。前台系统焦点与其他平台待实测。 [部分结果](evidence/iteration-45-47-space-cleanup-zh/i47-space-partial.jpg) |
| 分屏输入和尺寸 | Windows 已回放左右分屏、键盘限位与 Esc 取消。上下分屏、pointercancel、停靠 DevTools、系统辅助技术及重启恢复分别验收。目标布局需为各内容类型定义最小可用宽高。 |
| 托管协作状态 | 同一 Core 的第二次重连在 Settings 页等待 10 秒时仍未显示已连接，重新打开后恢复。验收需绑定服务就绪时刻，并并排核对标题栏协作和 Settings 的更新。 |
| 历史扫描部分可用 | 用有可恢复记录且会同时产生多个扫描提示的隔离档案，核对左栏提示展开、收起、窄窗结果命中及一次恢复。默认无提示的结果区已经回放。 |
| macOS / Linux / Windows ARM64 | Ubuntu x64 图形目录包在隔离 X11、Wayland Sway 与 GNOME Shell 中完成配对、SSH 接管、分支和读屏回放。GNOME Shell 实测使用独立的虚拟输出与临时登录密钥环。Linux 正式发行包、macOS 与 Windows ARM64 按各自安装和实际运行条件验收。 [GNOME 构建与条件](SOURCE_BASELINE.md#第-8183-轮来源) |

F01/F02 已完成第 90 轮（含第 2–3 次迭代修复与主进程英文词典/菜单、取消确认回焦及原控件禁用兜底、`TerminalSlide` 与设置回退文案对齐）桌面局部修复、Vitest 回归与 Windows 隐藏 Electron 实机核对（`A.04`、`B`、`B.01`、`B.05`、`L.04`、`M.01`、`N.orca-account`、`O.modal.onboarding`、`O.local.contextual-tour`）；本轮刻意未修改 F03 动效/主题体系、F04 保留工具及目标工作空间布局。物理手机扫码、受控 Porpita Cloud / `Porpita Relay` OAuth 与实时工件发布、以及系统可见前台窗口焦点等受环境限制项仍各自保留原边界待验。保留的 Orca 界面按各自理由继续验证。新发现的对象入 Inventory，覆盖行在取得相应状态和条件的证据后更新。

第 91 轮（Phase 1 Track A）完成受控 `<Dialog open>` 统一触发源回焦与嵌套/外部保护（`dialog-return-focus.ts`、`O.modal.add-repo`、`P.06`）、`button.tsx` 减少动效焦点环修复、`use-system-prefers-dark.ts` 实时媒体配色跟随、Settings `158%` 缩放与 `820×580` / `600×400` 响应式重构及 `zh`/`ja` 外观与 Kitty 导入词条补齐；Windows 隐藏窗口 Electron 实机覆盖 `N.appearance`、`O.modal.add-repo`、`P`、`P.01`、`P.02`、`P.03`、`P.06`、`P.07`、`P.10`、`P.12`、`P.13`、`Q`、`Q.01`、`Q.04`、`Q.05`。其余未在本轮实机采集的共享组件/动效子项（`P.04`、`P.05`、`P.08`、`P.09`、`P.11`、`Q.06`、`Q.07`）、系统可见窗口的 `WindowMaterial` 效果、原生读屏与 macOS/Linux 三端继续保持待验。

第四轮已有 Vault 的本地同名历史、原 Terminal Pane 和 Native Chat 导航证据。第五轮通过独立 Windows 档案复验本机与 Studio 配对、同 ID、来源撤回、断线重试与 Chat 回源。两台物理主机、直连 SSH、用户真实账号的权限变化、CLI 加载历史与跨 Host 布局仍待对应环境。 [第四轮](ITERATION_04.md) · [第五轮](ITERATION_05.md)
