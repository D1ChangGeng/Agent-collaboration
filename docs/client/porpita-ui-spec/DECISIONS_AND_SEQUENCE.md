# 决策、对照与分批实施

当前目标以参考包 D-001–D-009 为产品约束。表中结论是本次设计判断或后续证据条件，未记为用户最终确认。

| 决策 / 作用范围 | 证据与选择 | 下一次证据动作 |
| --- | --- | --- |
| DDU-01：保留 Orca 工具整体（E/F/H/I/J/P） | 当前 Porpita 同时保有原生 Chat、xterm、Monaco、Browser 和工作树工具；交付 11 对照与截图显示继承的布局和操作。VS Code 的工具/布局说明也支持把工具留在自己的区域。沿用实际组件、样式、操作所有者；不引入另一套组件语言 | 在可运行目标中逐工具对照长内容、权限、焦点和状态，核实未损失原生操作 |
| DDU-02：单击会话如何打开（C.10/D.07） | 候选：覆盖内容、保留旧内容加入焦点 Pane、每次开 Split。现有内容 Tab 支持保留；直接覆盖不利于草稿/运行可见，每次分屏在小窗侵占读区。推荐在 Pane 加入，已打开时定位 | 同一夹具对照活跃 Session、未保存草稿、键盘与拖动；记录窄窗和后退 |
| DDU-03：顶层组选择器（D.08） | Orca 顶栏已有横向 overflow；外部资料的折叠组、多行和溢出只作机制参考。以相同的 Orca TabBar 比较两案，420px 可用区中选择器保留更多当前标题；920px 时内联组名更容易扫视。[试验](GROUP_TRIAL.md) 后仍推荐一行选择器 | 第二轮 240/420/920px 及真实键鼠通过组件试验。生产窗口检查系统控制、固定、关闭、搜索、组间移动和恢复 |
| DDU-04：用户布局独立于执行环境（D.03/D.07） | `Tab` 的 worktree/host ownership、现有 close 与 retirement 和 per-worktree split 决定不能只改名称。复用 split、交互和生命周期守卫；引入独立布局记录并保存原内容引用 | 最小运行试验用两个本地 worktree 加两个 Host，验证已有 Chat 不重建、终端不被错误关闭、owner 不随聚焦变化 |
| DDU-05：面板固定 Scope 与移动（G） | Dock 当前按 Active worktree、folder/Git/SSH 与 plugin gate 分派；VS Code/IntelliJ 支持工具视图换位置，不能证明 Porpita 有通用实例。先 Explorer，Scope 固定。切换位置移动同一 Instance。Git/Checks/Ports 分别验收，插件先 Dock | 两棵文件树和同名路径跨 Host；移动与撤销保存查询、展开、滚动。插件若后续迁移先验证 frame token 和卸载 |
| DDU-06：首用和连接有各自状态（B/N.general/K） | 首用截图证实简中下仍有英文标题与引导，信任可与引导先后出现；未配置协作回放有专属动作，先前交付实测发现已连接/断开后设置状态滞后。保持引导和信任，修复文案与同源状态 | 完整向导、跳过、可信拒绝/允许（仅测试仓库）、连接和断线同时打开设置与协作，逐阶段检查同步 |
| DDU-07：多窗与短窗边界（A/D/M/P） | Windows 下原生主窗口下限 600×400；Dashboard/Space 独立窗口；参考包未锁定多主窗口。初代单主 owner，保留独立工具窗口 | 已运行工作对象在主窗与工具窗往返，记录焦点、输入归属和恢复；真多窗测试再决策 |
| DDU-08：动作回执（E/K/L/M） | Native execution、ACS 消息/投递、Host 可用性是不同权威。保留既有工具与状态文字；Session Index 投影独立的状态轴 | 用已读、等待审批、Host 断线与原生 ACK 同时存在的夹具复验，确保没有误报已处理或重复动作 |

外部机制参照（官方资料，未在 Porpita 集成）：[VS Code：工作台与编辑组](https://code.visualstudio.com/docs/editing/getting-started/userinterface) · [VS Code：自定义布局](https://code.visualstudio.com/docs/configure/custom-layout) · [IntelliJ IDEA：工具窗口模式](https://www.jetbrains.com/help/idea/viewing-modes.html) · [Chrome：标签页与标签组](https://support.google.com/chrome/answer/2391819)。Orca 自身是首选可采用的成熟来源；外部条目比较职责/操作，不借用外观或代码。未经同内容运行对照的候选留作推荐。

## 当前实测促成的调整

- **F01 / 窄窗可读性（A.02、D.03、G.01）**：EV22 在 820×580 显示 280px 左栏、350px 右栏与双 Pane 同时存在，中央约 190px；终端提示符只余数个字符。第二轮 820px 主区达到 320px。600px 只显示一栏，键盘交换可见侧，放宽恢复双栏及宽度。分屏下限和聚焦呈现进入目标 Workspace 设计。
- **F02 / 安全确认优先（O.01、O.local.trust、P.06）**：EV27 中新 toast 覆盖信任解释和按钮区域。工作区信任已启用避让，600×400 两个按钮可达。普通 Sheet 通过既有通知夹具。其他授权面先把自己的失败和重试放入对话框，再接入避让。
- **F03 / 空态与语言（B.01、B.05、M.01、N.appearance）**：EV01、EV06、EV15 的标题、引导或操作混中英。现有视觉分组保持。优先翻译用户下一步必读标题和动作；提供方名、代码和演示命令保留原文。EV16 的工件页引导去账户设置；S06 显示该安装版的产品登录不可用，故不可用状态应说明本机能做什么。两页分别进入检查，未执行登录。
- **F04 / 工作对象命名（C.05、K.01、D.07）**：EV31 的「创建工作区」包含运行 Host 和 Agent，而协作 Dialog 的「尚未连接工作区」下拉使用 ACS `project_id`。这些控件属于不同对象。保留布局与交互，明确「工作树/执行环境」「协作项目」「工作空间」三种目标，验证同名对象、切组与从消息跳回后仍能辨认来源。
- **F05 / 恢复与新功能提示（A.05、B.05、O.modal.feature-tips）**：同一测试档案退出并重开后，之前激活的 Markdown 内容已恢复；首个可见场景还可能有「搜索所有智能体会话」覆盖层。保留现有恢复和可关闭提示；复验焦点是否回到恢复的文档，并避免教育优先于正在工作或待处理的对象。
- **F06 / 混合窗口的状态栏归属（A.03、D.07.03）**：第 25 轮的窄窗同时有本机 Chat 和 Studio Explorer，底部用量仍显示 Studio。预览用量改为以所选 Chat 为来源。进入固定工具、原编辑器和账户设置时按实际工作对象切换或保留。端口与资源保留各自的范围验证。 [初始观察](evidence/iteration-24-26-loopback-zh/i25-narrow-workspace.png) · [第 27 轮](ITERATION_27.md) · [第 28 轮](ITERATION_28.md)
- **F07 / 端口和资源的各自归属（A.03、G.05）**：原端口入口有工作树刷新与跨 Host 汇总两种范围。预览端口取所选 Chat 或独立 Explorer 的工作树。资源管理器保留桌面快照与本机 PTY，并标明它们的范围。 [端口选择](ITERATION_30.md) · [本机资源](ITERATION_32.md)
- **F08 / 详情与定位（A.03、G.05）**：端口详情复用原对话框并显示 Host 与工作树。本机打开时先确认监听，再交给原工作树的 Browser。资源表定位后结束预览遮盖，返回仍可继续原预览。 [端口详情](ITERATION_33.md) · [资源定位](ITERATION_35.md)
- **F09 / 从诊断地址继续原标签（A.03.12–A.03.14、G.05、I.01）。** 先明确实际打开地址，再从失效详情回到原端口范围。Browser 开启后，将现有资源树行接到已有工作树和标签激活能力。Host、监听和标签分别取自身的身份。普通侧栏保有原端口入口。 [端口地址](ITERATION_36.md) · [原范围刷新](ITERATION_37.md) · [标签定位](ITERATION_38.md)
- **F10 / 进程定位与磁盘结果（A.03.15–A.03.16、M.02.01）。** 资源树和本机 PTY 共用原终端定位。预览定位到原输入窗格，暂时不能确认的绑定保留诊断。Space 用既有开窗请求结果决定何时结束资源弹层，失败留在同一摘要。 [终端窗格](ITERATION_39.md) · [PTY 状态](ITERATION_40.md) · [Space](ITERATION_41.md)
- **F11 / 批量选择、目录图与清理审阅（A.03.17、M.02.02–M.02.03）。** PTY 的全选表达可结束范围。Space 显示树图层级并在导航时交接键盘焦点。筛选保留工作树选择，审阅显示当前可见且合格的目标，主工作树按既有规则保护。 [PTY 选择](ITERATION_42.md) · [目录导航](ITERATION_43.md) · [清理审阅](ITERATION_44.md)
- **F12 / Space 审阅及清理回执（M.02.04–M.02.06）。** 首焦点在取消，返回点取本次审阅是否启动清理。结果按已确认移除的数量呈现，主窗口同步保留 Space 本地产生的失败状态。 [审阅焦点](ITERATION_45.md) · [完成结果](ITERATION_46.md) · [部分完成与重试](ITERATION_47.md)
- **F13 / Space 清理失败与保留分支（M.02.07–M.02.09）。** 先用已分类原因替代拥挤的原始错误，再从实际工作树清理回执汇集保留分支，最后复用校验 HEAD 和 Host 的分支复核。实施依赖前一轮的窗口状态合并、清理数量与焦点交接。 [失败原因](ITERATION_48.md) · [保留分支](ITERATION_49.md) · [分支复核](ITERATION_50.md)
- **F14 / Space 分支复核的拒绝与恢复（M.02.10–M.02.12）。** 继承确认后返回筛选的流程，先将分支结果接入原结果栏，再由 Git 读数区分分支变化和占用，最后让用户逐项继续复核或保留分支。 [批次结果](ITERATION_51.md) · [拒绝原因](ITERATION_52.md) · [继续处理](ITERATION_53.md)
- **F15 / 从检出占用返回原复核（M.02.13–M.02.15）。** 先用 Git 的实读路径说明占用位置，匹配登记实例后复用工作台打开行为。保持原复核与选择，用户处理后显式提交，仍由 Git 确认实际结果。 [检出路径](ITERATION_54.md) · [工作树交接](ITERATION_55.md) · [返回复核](ITERATION_56.md)
- **F16 / 主工作台回到原 Space 复核（M.02.16–M.02.18）。** 主窗口以现有状态栏持续显示返回动作，由收到回复的复核恢复原焦点。入口随这次复核和 Space 文档寿命同步回收。 [返回入口](ITERATION_57.md) · [原复核焦点](ITERATION_58.md) · [生命周期](ITERATION_59.md)
- **F17 / 工作树变化后的 Space 复核（M.02.19–M.02.21）。** 实际 Git 移动使原按钮离开界面，复核仍可返回。成功提示跟随实际打开的实例，旧路径用独立文案说明。已保留分支在显式提交时取 Git 的当前占用与删除结果。 [焦点回退](ITERATION_60.md) · [上次路径](ITERATION_61.md) · [再提交](ITERATION_62.md)
- **F18 / 复核内核对 Git 检出（M.02.22–M.02.24）。** 沿用原分支行和本机清理目标，引入只读检出读数。未检出时保持勾选，HEAD 变化时沿用保留分支处理，提交仍消费实际 Git 回执。 [当前路径](ITERATION_63.md) · [核对状态](ITERATION_64.md) · [再次占用](ITERATION_65.md)
- **F19 / 配对主机与 WSL 的 Git 复核（M.02.25–M.02.27）。** 复用分支对话框与工作台通知。待清理记录约束原配对，断线留在原行，失败回执回到零选复核。Space 中的本机 WSL 项目沿用对应发行版的 Git 和路径。 [配对主机](ITERATION_66.md) · [连接与重试](ITERATION_67.md) · [WSL 路径](ITERATION_68.md)
- **F20 / 在原复核恢复主机（M.02.28–M.02.30）。** 行内动作复用既有连接和 WSL 启动机制，取得确认的 Git 结果后恢复该项提交。独立 SSH 的现有对话框提供项目接入入口。 [配对](ITERATION_69.md) · [SSH](ITERATION_70.md) · [WSL](ITERATION_71.md)
- **F21 / 双机配对与 SSH 接管（M.02.31–M.02.33）。** 先核对两端产物和实际服务身份，再复用现有接管。接管后的分支复核使用原 Host 的 Git，修订集中在 SSH 连接错误与重试回执。 [配对](ITERATION_72.md) · [接管](ITERATION_73.md) · [复核与重试](ITERATION_74.md)
- **F22 / Linux 原生键盘与读屏（M.02.34–M.02.36）。** 先部署同版本图形客户端并核对双机配对。以原 Worktrees 焦点定位工作区，沿用 SSH 卡片状态和分支复核。用实际系统播报对照对话框返回、接管进度和 Git 回执。 [配对](ITERATION_75.md) · [SSH 接管](ITERATION_76.md) · [分支复核](ITERATION_77.md)
- **F23 / Wayland 回放、Git 回执与卡片避让（M.02.37–M.02.38、O.01.01）。** 先用 Wayland 原生键码核对原有键盘路径。在复核框退出后按实际 Git 状态发布或更新通知，让 Orca 与画面取得同一条回执。终端工作台沿用首次使用卡片，进入设置或模态复核时暂停显示，返回后接续。 [Wayland 原生输入](ITERATION_78.md) · [成功回执](ITERATION_79.md) · [卡片避让](ITERATION_80.md)
- **F24 / GNOME Shell 焦点交接、回执与平铺（M.02.39–M.02.40、O.01.02）。** 由 GNOME 接收系统快捷键，回到 Porpita 保留原表单或复核焦点。用一次提交核对 Git 回执，并用窗口平铺验证 SSH 控件以及卡片的暂隐和恢复。 [系统快捷键](ITERATION_81.md) · [读屏回执](ITERATION_82.md) · [平铺避让](ITERATION_83.md)
- **F25 / 同前缀 SSH 目标的辨识、选择和确认（M.04.02–M.04.04）。** 保留 SSH Hosts 的现有行、控件与连接生命周期。宽度不足时让别名、地址和操作区在条目内换行。用可见文案为按键控件提供上下文，连接后在同一行显示状态并读出完整身份。 [目标辨识](ITERATION_84.md) · [键盘选择](ITERATION_85.md) · [连接确认](ITERATION_86.md)
- **F26 / 导入的 IPv6 身份和首次确认（M.04.05–M.04.07）。** 复用 OpenSSH 路由解析补齐导入身份，在列表及握手弹层使用同一 IPv6 地址格式。将 `ask` 的首次未知密钥送入现有 SSH 请求队列，用户确认后按实际握手身份保存。 [导入](ITERATION_87.md) · [IPv6](ITERATION_88.md) · [主机密钥](ITERATION_89.md)

第六至八轮的英文浅色回放仍显示「Orca Mobile」，简中深色显示「Porpita 手机端」。两者进入同一配对入口。该处导航文案与真正的上游下载链接需要分别核对，按 M.01 的语言与移动交接场景复验。 [英文侧栏](evidence/iteration-07-windows/i7-keyboard.json) · [简中侧栏](evidence/iteration-08-windows-zh/i8-worktree-return.json)

## 实施顺序与回归

| 顺序 / SPEC | 设计职责和完成依据 | 覆盖 ID / 回归 |
| --- | --- | --- |
| 00 当前产品基线 | Inventory、矩阵、源码与安装版证据冻结，遗漏按 ID 加回；先修复分类错误 | A–T / J01–J13 |
| 01 找到并继续真实会话 | 预览左栏接入未开历史续接、运行状态与按 Host 选择，协作通过原授权项目进入。混合 Workspace 中的已开会话通过目录定位原 Pane。ACS 来源逐条关联、规模化目录和多物理 Host 仍需对应证据。 [第十八轮](ITERATION_18.md) · [第二十轮](ITERATION_20.md) · [第 21 轮](ITERATION_21.md) | C、E、F、G、K、N.session-history / J02,J03,J05,J06,J09,J12 |
| 02 组织并恢复并行工作 | 保留桌面布局的分组和拖放。扩展双 Host Pane、v2 来源限定档案和单侧恢复。后续用受控 Harness 验证实际发送及审批、多物理设备和终端、浏览器的保留机制。 [第十四轮](ITERATION_14.md) · [第 22 轮](ITERATION_22.md) · [第 23 轮](ITERATION_23.md) | A、D、P、Q / J03,J04,J06,J13 |
| 03 固定范围的工具面板 | 预览接通本机和配对 Runtime 的固定根，复用逐目录浏览、名称筛选、放置菜单和原编辑器。v3 保留来源与位置。端口地址与失效刷新依赖原工作树和 Host 解析，资源定位依赖已经注册的 Browser 标签和分组。完整 Explorer 树、Contents 与 Git 写入按各自权限扩展。 [第 24–26 轮](ITERATION_24.md) · [第 36–38 轮证据](evidence/README.md#第-3638-轮) | A、G、H、I / J04,J07,J08,J10–J13 |
| 04 进出工作台的全域体验 | 首用/设置、协作、任务、自动化、插件、远程、独立窗口；各有独立页面审查和真实任务证据 | B、I–O / J01,J02,J07–J13 |
| 05 全域复核 | 适用主题/语言/平台/状态、动效和跨对象流程逐项闭环；修复回放发现并复查同族 | A–T / 全部 |

无改动的面保留各自目标、理由、源码和回归。迁移时先读取旧 Worktree 布局，保留原 profile 保存和回退；目标布局的保存失败不能破坏原生会话/旧布局。每次变更核对覆盖的条件与状态。第二轮已先修复现有工作台宽度和工作区信任遮挡，目标组织模型按表中依赖推进。

## 参考包交付物、开放问题与决策交叉对照

### 参考包 11 项交付物映射

`RFC_TEMP_SOURCE/Porpita-Workspace-UI-Spec-Reference-v1.0.0/` 中规定的 11 项 UI SPEC 交付物已全部落入现行 `porpita-ui-spec/` 目录与设计证据链，逐一映射如下：

| 参考包交付物 | 现行权威文档与落位 | 覆盖核心内容与轮次收口 |
| --- | --- | --- |
| `UI_SPEC_SUMMARY.md` | [README.md](README.md) · [COVERAGE_CLOSURE.md](COVERAGE_CLOSURE.md) | 20 域 371 项全客户端范围总结、M1–M4 分批收敛结果与 `ENV_BOUNDED` 诚实边界 |
| `OBJECT_MODEL.md` | [WORKSPACE_INTERACTION_SPEC.md](WORKSPACE_INTERACTION_SPEC.md) | `Native Session`、`ACS Conversation`、`Porpita Workspace`、`Pane`、`Top-level Tab`、`Tab Group` 与 `SidePanel Definition/Instance` 权威边界 |
| `INTERACTION_SPEC.md` | [WORKSPACE_INTERACTION_SPEC.md](WORKSPACE_INTERACTION_SPEC.md) · [VISUAL_INTERACTION_SYSTEM.md](VISUAL_INTERACTION_SYSTEM.md) | 点击、键盘焦点、Split 调宽/Esc、IME、覆盖层退让与错误/离线/草稿保护契约（第 90–94 轮） |
| `ORCA_REUSE_MAP.md` | [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) · [VISUAL_INTERACTION_SYSTEM.md](VISUAL_INTERACTION_SYSTEM.md) | 保留／改造／新增处置矩阵（`A`–`T`）及 32 项基础组件包装使用索引 |
| `SIDEPANEL_CAPABILITY_MATRIX.md` | [SIDEPANEL_CAPABILITY_MATRIX.md](SIDEPANEL_CAPABILITY_MATRIX.md) | 保留同名的独立与嵌入能力矩阵（`G.01`–`G.09`），率先落地固定 Scope Explorer |
| `SESSION_INDEX_SPEC.md` | [WORKSPACE_INTERACTION_SPEC.md](WORKSPACE_INTERACTION_SPEC.md) | Sidebar `SidebarSessionIndex` 发现、位置/项目/Host 筛选与 ↔ Vault 历史接续（第 94 轮 `C.10`–`C.10.09`、`R.03`） |
| `TAB_GROUP_SPEC.md` | [GROUP_TRIAL.md](GROUP_TRIAL.md) · [WORKSPACE_INTERACTION_SPEC.md](WORKSPACE_INTERACTION_SPEC.md) | 一行 Group Selector 对照实验与 `General/通用` 防误删、溢出及拖拽防误移（第 94 轮 `D.08`–`D.08.02`） |
| `WORKSPACE_LAYOUT_SPEC.md` | [WORKSPACE_INTERACTION_SPEC.md](WORKSPACE_INTERACTION_SPEC.md) | 双会话分屏、`< 646px` 容器切换与 `porpita-workspaces.json` v3 冷启动恢复／损坏回退（第 94 轮 `D.07`–`D.07.05`、`A.05`） |
| `PLAYBACK_SCENARIOS.md` | [PLAYBACK_SCENARIOS.md](PLAYBACK_SCENARIOS.md) · [evidence/README.md](evidence/README.md) | 保留同名的 `J01`–`J13` 验收旅程规范与第 02–94 轮实机运行记录及截图 |
| `OPEN_QUESTIONS.md` | 本文下节「Open #1–#12 研究收敛矩阵」与 [COVERAGE_CLOSURE.md](COVERAGE_CLOSURE.md) | 对 `DECISIONS_AND_OPEN_QUESTIONS.md` 全部 12 项开放问题的实验选择、源码落位与待验边界 |
| `DECISION_LOG.md` | 本文 `DDU-01`–`DDU-08` 与 `F01`–`F26`（承接参考包 `D-001`–`D-009`） | 产品裁决理由、实机回放促成的 26 项迭代调整与实施顺序 `00`–`05` |

### 参考包 Open Questions（Open #1–#12）研究收敛矩阵

以下对应参考包 `DECISIONS_AND_OPEN_QUESTIONS.md` 全部 12 项 `Open #1`–`Open #12` 待研究问题：

| 开放问题 | 原始研究问题 | 现行设计与集成结论 | 证据／矩阵锚点与保留边界 |
| --- | --- | --- | --- |
| Open #1 | Tab Group 是 Group Selector 还是同一横向 Tab Strip 分组呈现？ | 已确定采用标题栏单行 **Group Selector**（[GROUP_TRIAL.md](GROUP_TRIAL.md) 420px/920px 对照实验与 `DDU-03`），第 94 轮已纳入默认生产构建 | `A.02`、`D.08.01`、`[第 94 轮](ITERATION_94.md)`；窄窗收缩至 44px 无溢出 |
| Open #2 | 现有 Orca Tabs 是 per-worktree 内容 Tab；如何最小化抽取为 Porpita top-level Workspace Tab？ | 保留内容层 per-worktree Tabs，引入独立顶层 `Workspace` / `Standalone SidePanel` Tab 模型并区分两层命令；第 94 轮已移除 `VITE_PORPITA_WORKSPACE_PREVIEW` 门控并原生集成 | `D.01`、`D.07`、`D.08`、`A.02`、`T.06`；内容层与顶层快捷键各自独立 |
| Open #3 | 跨 Worktree / Project Session 能否复用当前 Pane Tree？是否需要独立 Layout Owner？ | 引入独立 Porpita Workspace Layout Owner，按 Host + Worktree + Session 稳定引用绑定每个 Pane，复用现有 Split 绘制与键盘逻辑（`DDU-04`） | `D`、`D.03`、`D.07.03`、`D.07.04`；跨两台真实物理机异网分屏继续归 `EB-03` |
| Open #4 | Session 单击的最终默认：替换焦点 Pane、打开新 Tab 还是复用/激活？ | 已激活对应会话时直达原 Workspace 与 Pane；未打开时默认加入当前焦点 Pane（保留已有内容 Tab），无 Workspace 时新建单 Session Workspace（`DDU-02`） | `C.10`、`C.10.02`、`C.10.03`、`R.03`；支持右键与拖拽显式分屏／新工作空间 |
| Open #5 | SidePanel 哪些类型具备 Standalone / Embedded 资格？ | 按 `SIDEPANEL_CAPABILITY_MATRIX.md` 分批收敛：第 94 轮已默认集成具备 Standalone ↔ Embedded 能力的 **Explorer**；Source Control/Checks/Ports/Vault 先评估固定 Scope，Plugin Panels/Attached worktrees/PR Checks 初代维持 Dock only（`DDU-05`） | `G.01`–`G.09`、`G.09.01`、`R.07`、`[能力矩阵](SIDEPANEL_CAPABILITY_MATRIX.md)` |
| Open #6 | Explorer / Source Control 等依赖 activeWorktree 的面板如何固定 Scope？ | 将显式 `Host + Worktree/Repo/Root` 提升至 `SidePanel Instance` 元数据与 v3 持久化结构中，禁止默认跟随焦点会话切换；切到其他仓库时 Explorer 保持原 Scope（第 94 轮实测通过） | `G.02`、`G.09.01`–`G.09.04`、`R.07`；多级完整树写回与 Source Control 独立宿主按 `G.03` 推进 |
| Open #7 | Plugin Panel 能否安全重挂载到不同 Host？ | 当前保持 Dock only 与按 `tabKey` + session token 隔离的 iframe/声明式生命周期（第 92 轮修复 `orca-runtime.mjs` 与停用恢复焦点），在尚未通过多实例桥接卸载验真前禁止跨宿主移动（`G.08`） | `G.08`、`L.06`、`N.plugins`、`[第 92 轮](ITERATION_92.md)` |
| Open #8 | 同一 SidePanel Definition 多 Instance 的状态隔离策略。 | 采用 `Definition + Explicit Scope` 复用与独立 `Instance ID` 隔离内部查询、筛选、选中与滚动，同一 Instance 仅允许唯一活跃宿主呈现（`G.09`） | `G.02.02`、`G.09`–`G.09.04`、`[能力矩阵](SIDEPANEL_CAPABILITY_MATRIX.md)` |
| Open #9 | Tab Group 在窄窗口和大量 Tab 下的最佳视觉形态。 | Group Selector 限制 `max-w-[min(132px,31%)]` 并于 600×400 窄窗压缩至 `44px`，配合 20+ 标签横向可滚动溢出与「打开工作对象」全量列表，完整组名保留于下拉菜单与可访问名称（第 94 轮实测） | `A.02`、`D.01`、`D.08`、`D.08.01`、`[第 94 轮](ITERATION_94.md)` |
| Open #10 | 多窗口下 Workspace / Session 的唯一性与恢复策略。 | 初代维持单主 Workspace 窗口 owner（Dashboard / Space 为独立辅助工具窗口，`DDU-07`），由主进程 `porpita-workspaces.json` v3 原子持久化并在损坏 JSON 时提示 Retry / Reset layout；同一稳定 Session 引用禁止多处并发输入 | `A.05`、`A.06`、`D.07.02`、`D.07.04`、`R.06`；物理多主窗口并发协同留待真多窗阶段验证 |
| Open #11 | Workspace 默认命名、重命名与 Project affinity 提示。 | 默认命名取首次进入的会话/范围，允许用户显式重命名；`General` / `通用` 为默认系统保护组禁止改名或删除；协作对话框区分「协作项目」与「执行工作区」，工作空间不强制绑定 Project（`F04`） | `C.05`、`D.07`、`D.08`、`D.08.01`、`K.01` |
| Open #12 | Session Index 的状态摘要、未读归属和 Needs Attention 规则。 | 将 **运行**（Native/Host）、**通信**（ACS 未读/投递阶段）与 **Host 可用性** 三轴分离投影（`DDU-08`），Needs Attention 聚合待处理原生输入、未读协作与恢复阻断，点击已读不篡改运行状态；第 93/94 轮集成左栏索引、RunState 徽标及 ACS 未读实时同步 | `C.10`、`C.10.07`、`C.10.08`、`K.02`、`K.04`、`R.03`、`R.09` |

## ORCA-FIRST 架构基线、UX01–UX22 与 ACS 通信合同交叉引用

1. **Client 路线基线双向对照（[ORCA-FIRST.zh-CN.md](../ORCA-FIRST.zh-CN.md)）**：完整保留 2026-11-06 建筑原则及第 9 节原位归档，并在该文档第 11 节将全部 **12 项路线实机基线（`T01`–`T12`）** 与 **22 项交付验收场景（`UX01`–`UX22`）** 双向映射至本目录的 `J01`–`J13`、`K.*`、`C.10.*`、`D.*`、`G.09.*` 与第 90–94 轮证据及 `COVERAGE_CLOSURE.md`（参见 [ORCA-FIRST 双向映射](../ORCA-FIRST.zh-CN.md#11-现行实现状态与双向交叉引用)）：
   - 核心对应概览：`T01`、`T02`（`UX04`、`UX05`）→ `K`、`K.01`–`K.04`、`D.07.01`、`D.07.03`、`J04`/`J05`/`J09`；`T03`、`T04`、`T05`（`UX06`、`UX07`、`UX08`、`UX09`、`UX11`、`UX15`、`UX16`、`UX17`）→ `A.05`、`D.07.02`/`D.07.05`、`K.01`–`K.04`、`N.general.01`、`S.07`/`S.08`、`J06`/`J09`/`J12`；`T06`（`UX02`、`UX03`、`UX10`、`UX14`）→ `C.10.03`–`C.10.06`、`G.06`、`D.08`、`J03`/`J05`/`J06`；`T07`、`T12`（`UX01`、`UX13`、`UX18`、`UX19`、`UX20`、`UX21`）→ `A.03.05`、`C.10.09`、`E.09`、`G.09.04`、`M.02.25`–`M.02.37`、`P`/`Q`、`J01`/`J07`/`J10`–`J13`；`T08`（`UX22`）→ [SOURCE_BASELINE.md](SOURCE_BASELINE.md)、[COVERAGE_CLOSURE.md](COVERAGE_CLOSURE.md) 与 [design-evidence.json](../../../.ui-spec/design-evidence.json)；`T09`、`T10`、`T11`（`UX12`、`UX18`）→ `A.03.02`、`G.08`、`L.05`/`L.06`、`N.plugins`、`J10`。
2. **ACS 通信客户端合同锚点**：
   - 全量客户端通信合同：[communication-openapi.yaml](../communication-openapi.yaml)
   - P1 核心必需子集合同：[communication-p1-openapi.yaml](../communication-p1-openapi.yaml)
   - 操作范围分级清单：[communication-api-scope.json](../communication-api-scope.json)（总计 `35` 个 `operationId`，其中 `22` 个 `P1_required`、`13` 个 `P2_optional`，`K.01`–`K.04` 与第 93 轮 `p1_only` 轮询降级严格遵循该范围划分）
   - 契约采纳与字段修正声明：[communication-contract-adoption.json](../communication-contract-adoption.json)（Schema `acs-client-contract-adoption/1`，锁定 `Draft` rev-0 `updated_at: null`、`Notice` 历史空值、`Meta.limits` 配额与原生链接预算、`NativeLinkWrite` 主机代次防错写，以及 `ReadMessageResponse.native_source` 只读溯源边界，对应 `K.03`、`K.04` 与 `UX10`/`UX11`/`UX12`/`UX16`）
3. **机器可读结构化设计证据**：[.ui-spec/design-evidence.json](../../../.ui-spec/design-evidence.json)（由 `check_design_evidence.py` 验证通过 `overview` / `detail` / `execution` 全视图，零结构发现项 `structural_findings: []`）。
