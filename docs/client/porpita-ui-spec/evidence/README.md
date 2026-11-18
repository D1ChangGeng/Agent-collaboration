# 现版观察与回放证据

## 第 90 轮

Windows x64 在隔离档案与隐藏 Electron 窗口（`ORCA_BACKGROUND_LAUNCH=1`、`ORCA_E2E_HEADLESS=1`，全部 `!visible && !focused`）运行 `tools/observe-round-90.cjs`，对默认生产模式构建采集 23 组英/简中宽窄屏证据，覆盖 F01 与 F02 修复项。 [运行记录](iteration-90-windows/run.json) · [构建与测试条件](../SOURCE_BASELINE.md#第-90-轮来源)

| 范围 | 证据 |
| --- | --- |
| F01 向导焦点、语言与窄窗（`B`、`B.01`、`O.modal.onboarding`） | [英文向导](iteration-90-windows/i90-en-onboarding-agent-surface-1280.json) · [简中向导](iteration-90-windows/i90-zh-onboarding-agent-surface-1280.json) · [简中 Agent](iteration-90-windows/i90-zh-onboarding-agent-1280.json) · [简中主题](iteration-90-windows/i90-zh-onboarding-theme-1280.json) · [窄窗 600×400](iteration-90-windows/i90-zh-onboarding-narrow-600.json) |
| F01 首页与导览（`A.04`、`B.05`、`O.local.contextual-tour`） | [英文首页](iteration-90-windows/i90-en-landing-1280.json) · [简中窄窗首页](iteration-90-windows/i90-zh-landing-narrow-600.json) · [英文窄窗导览](iteration-90-windows/i90-en-tour-narrow-600.json) · [简中窄窗导览](iteration-90-windows/i90-zh-tour-narrow-600.json) |
| F02 移动端、工件与账户（`M.01`、`L.04`、`N.orca-account`） | [英文配对](iteration-90-windows/i90-en-mobile-pairing-1280.json) · [简中配对](iteration-90-windows/i90-zh-mobile-pairing-1280.json) · [简中终端示例](iteration-90-windows/i90-zh-mobile-terminal-slide-1280.json) · [英文工件不可用](iteration-90-windows/i90-en-artifacts-unavailable-1280.json) · [简中工件不可用](iteration-90-windows/i90-zh-artifacts-unavailable-1280.json) · [简中工件设置](iteration-90-windows/i90-zh-settings-artifacts-1280.json) · [简中账户设置](iteration-90-windows/i90-zh-settings-account-1280.json) |

## 第 87–89 轮

三个同前缀条目由隔离的 `~/.ssh/config` 导入，各自使用 IPv6 环回端口和专用 Ed25519 主机密钥。GNOME Shell Wayland 将应用平铺到 720px，Orca 51.1 记录键盘选择与确认。基线五个检查点，修订版九个。 [基线](iteration-87-89-gnome-baseline/run.json) · [最终实机回放](iteration-87-89-gnome-en/run.json) · [构建与测试条件](../SOURCE_BASELINE.md#第-8789-轮来源)

| 轮次 | 证据 |
| --- | --- |
| 87 | 使用键盘同步配置并核对来源分组。三个完整端点与 `ssh -G` 一致，包括通配 `Host` 规则继承的用户名。 [导入前后核对](iteration-87-89-gnome-en/i87-import.json) |
| 88 | 720px 下三个完整别名与 `用户名@[::1]:端口` 一起可见。Orca 逐条读出完整身份。 [读取记录](iteration-87-89-gnome-en/i88-focus-beacon.json) · [原生录音](iteration-87-89-gnome-en/config-host-focus.wav) |
| 89 | 首次弹层默认聚焦 Cancel，显示本次握手的目标和真实指纹。Escape 后认证与信任表保持原值。显式确认后仅 Beacon 认证并写入端点记录，重连复用信任。 [取消](iteration-87-89-gnome-en/i89-cancel.json) · [确认录音](iteration-87-89-gnome-en/host-key-confirmation.wav) · [认证记录](iteration-87-89-gnome-en/i89-connected.json) · [重连](iteration-87-89-gnome-en/i89-reconnected.json) |

## 第 84–86 轮

同一物理 Ubuntu 验收机在 GNOME Shell Wayland 的 1440×900 虚拟输出提供 1440px 与 720px 客户端宽度。基线有 4 个检查点，最终 Porpita 0.1.0 有 8 个。三个同前缀主机使用预登记密钥、独立 IPv4 回环地址和非默认端口。 [基线运行](iteration-84-86-gnome-baseline/run.json) · [最终运行](iteration-84-86-gnome-en/run.json) · [构建与条件](../SOURCE_BASELINE.md#第-8486-轮来源)

| 轮次 | 证据 |
| --- | --- |
| 84 | 720px 基线的别名与地址均截短。修订版能查看三条完整身份，连接动作随条目换行。 [修订前](iteration-84-86-gnome-baseline/i84-baseline-beacon.png) · [修订后](iteration-84-86-gnome-en/i84-tiled.png) |
| 85 | Orca 逐条读出连接动作、完整别名、用户名、IP 和端口。Space 勾选 atlas，前后 Tab 保持条目可辨。 [基线录音](iteration-84-86-gnome-baseline/baseline-focus.wav) · [修订版录音](iteration-84-86-gnome-en/host-focus.wav) · [勾选记录](iteration-84-86-gnome-en/i85-bulk-selection.json) |
| 86 | 在 beacon 的按钮按一次 Enter，仅其监听新增 TCP 和公钥认证。Orca 读出带同一目标的 Connected 语句，焦点贯穿连接和断开。 [连接画面](iteration-84-86-gnome-en/i86-connected.png) · [三个监听的核对记录](iteration-84-86-gnome-en/i86-connected.json) · [确认录音](iteration-84-86-gnome-en/connection-confirmation.wav) |

首次修订的语音轨迹保留了 Connected 与别名粘连的现象。最终录音与状态句用于核对修订。 [试跑](iteration-84-86-gnome-trial/i86-connected.json)

## 第 81–83 轮

Porpita 0.1.0 在物理 Ubuntu 验收机的独立 GNOME Shell 46.0 / Mutter 46.2 Wayland 会话运行。21 个检查点使用 1440×900 合成器输出、英语浅色和 US 键盘布局。GNOME Orca 51.1 通过 AT-SPI 2.62.1 播报，Windows 对端使用同一提交。 [运行记录](iteration-81-83-gnome-en/run.json) · [版本](iteration-81-83-gnome-en/orca-version.txt) · [构建与条件](../SOURCE_BASELINE.md#第-8183-轮来源)

| 轮次 | 实机结果 |
| --- | --- |
| 81 | Super、Super+V 及 Super+Tab 在 GNOME 生效。回到 Porpita 后保持配对表单输入焦点，应用内 Escape 再关闭表单。键盘完成 Windows 配对和独立 SSH 接管，Alt+T 进入应用内通知。 [概览](iteration-81-83-gnome-en/i81-activities.png) · [系统通知](iteration-81-83-gnome-en/i81-system-notifications.png) · [切回表单](iteration-81-83-gnome-en/i81-switch-return.json) |
| 82 | Git 复核中打开及退出系统通知，保留选中分支与确认焦点。只按一次 Enter，Orca 自动读出一次「Git branches deleted: 1」。 [恢复复核](iteration-81-83-gnome-en/i82-review-resumed.png) · [语句](iteration-81-83-gnome-en/i82-automatic-receipt.json) · [录音](iteration-81-83-gnome-en/i82-receipt-voice.wav) · [Windows 对端](iteration-81-83-gnome-en/windows-peer-proof.json) |
| 83 | GNOME 平铺将客户端宽度从 1440px 缩到 720px。SSH「连接」保有焦点和中心命中，卡片在设置及模态期间暂隐，返回后恢复。 [最大化](iteration-81-83-gnome-en/i83-ssh-before-tile.png) · [平铺](iteration-81-83-gnome-en/i83-ssh-settings.png) · [工作台卡片](iteration-81-83-gnome-en/i83-card-returned.png) |

试跑记录保留新档案的 GNOME 密钥环提示。正式回放使用已初始化的临时登录密钥环与独立项目标识。 [密钥环提示](iteration-81-83-gnome-trial/startup-keyring-prompt.png)

## 第 78–80 轮

Windows x64 与物理 Ubuntu x86_64 运行同一提交的 Porpita 0.1.0。Linux 使用隔离 Sway 1.9，Porpita surface 为 Wayland `xdg_shell`，XWayland 关闭。GNOME Orca 51.1 经 AT-SPI 2.62.1 与 Speech Dispatcher 播报。英语浅色 1060×790 的十四个检查点保存合成器截图、焦点和读屏记录。 [运行记录](iteration-78-80-wayland-en/run.json) · [Orca 与 AT-SPI 版本](iteration-78-80-wayland-en/orca-version.txt) · [图形包来源](../SOURCE_BASELINE.md#第-7880-轮来源)

| 轮次 | 证据 |
| --- | --- |
| 78 | 原生键盘完成取消回焦、双机配对、独立 SSH 接管和分支复核。Alt+T 进入通知区。工作树路径移动后，复核在实际断线时保留选择和焦点，Orca 播报原行重连动作。恢复后 Git 拒绝删除再次被检出的分支。 [配对](iteration-78-80-wayland-en/i78-windows-paired.png) · [接管](iteration-78-80-wayland-en/i78-adopted-ssh-host.json) · [断线录音](iteration-78-80-wayland-en/i78-outage-voice.wav) · [Git 拒绝](iteration-78-80-wayland-en/i78-git-refusal.json) |
| 79 | 最终重试只按一次 Enter。GNOME Orca 随后自动播报一次「Git branches deleted: 1」。Linux 删除目标引用，Windows 同名引用保留。 [画面](iteration-78-80-wayland-en/i79-automatic-receipt.png) · [播报事件](iteration-78-80-wayland-en/i79-automatic-receipt.json) · [声音](iteration-78-80-wayland-en/i79-receipt-voice.wav) · [对端 Git](iteration-78-80-wayland-en/windows-peer-proof.json) |
| 80 | 同一合成器和尺寸下，基线的卡片覆盖 SSH「连接」按钮中心。修订后按钮中心命中，Tab 焦点可见。设置和分支复核中卡片避让，返回工作台后恢复。 [基线](iteration-78-80-wayland-trial/i80-ssh-settings.png) · [修订画面](iteration-78-80-wayland-en/i80-ssh-settings.png) · [按钮命中](iteration-78-80-wayland-en/run.json) · [卡片恢复](iteration-78-80-wayland-en/i80-card-returned.png) |

基线用 wtype 发 Alt+T 时字母被分配到临时键码，最终版采用与 US 布局一致的 evdev 键码复核物理快捷键。第一次回执修订的 Orca 输出将已过期的进度读入成功语句，该轮结果留作回归证据。 [遮挡试跑](iteration-78-80-wayland-trial/run.json) · [混合播报](iteration-78-80-wayland-trial/i79-stale-progress-speech.json) · [键码实现](../tools/wayland-evdev-key.c)

## 第 75–77 轮

同提交的 Porpita 0.1.0 在 Windows x64 和物理 Ubuntu x86_64 上运行。Linux 使用已部署图形包、独立 X11，会话启用 GNOME Orca 46.1 与真实语音输出。十步回放使用英语浅色，窗口 1060×790。截图为原生 X11 根窗口像素。 [回放](iteration-75-77-linux-en/run.json) · [Windows 对照](iteration-75-77-linux-en/windows-peer-proof.json) · [产物](../SOURCE_BASELINE.md#第-7577-轮来源)

| 轮次 | 回放结果 |
| --- | --- |
| 75 | 原生键盘打开配对表单，Escape 回到原按钮。再次打开后确认隧道，连接 Windows Runtime。Orca 播报字段说明和连接结果。 [配对表单](iteration-75-77-linux-en/i75-pair-dialog.png) · [取消回焦](iteration-75-77-linux-en/i75-pair-cancel.png) · [配对结果与播报](iteration-75-77-linux-en/i75-windows-paired.json) |
| 76 | 方向键和删除快捷键打开独立 SSH 项目确认，再进入 SSH 设置接管原项目。Orca 读出连接动作与 Connected，焦点留在同一按钮位置。 [接管前](iteration-75-77-linux-en/i76-original-ssh-workspace.png) · [接管后的焦点与播报](iteration-75-77-linux-en/i76-adopted-ssh-host.json) |
| 77 | Alt+T 进入保留分支通知。复核核对真实移动路径，断线时保留选择和焦点，Orca 读出复核行重连动作及恢复后的 Git 结果。再次占用触发拒绝。显式重试后只删除 Linux 目标引用，通过通知列表读取成功回执。 [断线画面](iteration-75-77-linux-en/i77-original-row-outage.png) · [断线录音](iteration-75-77-linux-en/i77-outage-voice.wav) · [恢复](iteration-75-77-linux-en/i77-original-row-recovered.json) · [失败回执](iteration-75-77-linux-en/i77-git-refusal.json) · [成功回执与播报](iteration-75-77-linux-en/i77-explicit-retry-result.json) |

保留初次回放的 Escape 焦点、SSH 键盘入口和 Alt+T 未转移的记录。第一次成功重试已在 UI 显示回执，播报事件中未出现该行。补验使用 Alt+T、Tab 和 Orca 的当前位置查询，确认实际读出「Git branches deleted: 1」。 [键盘试跑](iteration-75-77-linux-trial/keyboard-trial-run.json) · [通知焦点试跑](iteration-75-77-linux-trial/terminal-notification-focus.json) · [自动播报观察](iteration-75-77-linux-trial/i77-explicit-retry-result.json) · [GNOME Orca 命令](https://gnome.pages.gitlab.gnome.org/orca/help/gl/commands_where_am_i.html)

## 第 72–74 轮

Windows x64 客户端与物理 Linux x86_64 运行端使用同一 Porpita 0.1.0 提交。双机通过 OpenSSH 建立实际连接。独立 SSH 项目有自己的托管 Runtime，使用接管前已存在的 Git 仓库与工作树。回放采用 Windows 隐藏 Electron 窗口、1000×720、英语浅色，记录实际 Runtime ID、Git 回执和键盘焦点。 [运行记录](iteration-72-74-physical-en/run.json) · [断言](iteration-72-74-physical-en/physical-porpita-checks.json) · [产物来源](../SOURCE_BASELINE.md#第-7274-轮来源)

| 轮次 | 实际结果 |
| --- | --- |
| 72 | 在服务器设置输入 Linux 运行端生成的访问链接，确认 SSH 隧道。连接后比对实际版本与 Runtime ID。 [配对完成](iteration-72-74-physical-en/i72-physical-pairing.png) |
| 73 | 原工作区确认进入对应 SSH 设置。连接后原项目 ID 与仓库路径保持，项目由独立的托管 Runtime 提供。 [接管前](iteration-72-74-physical-en/i73-standalone-project-before-adoption.png) · [接管后](iteration-72-74-physical-en/i73-adopted-server.png) |
| 74 | Linux Git 读到工作树移动后的路径。断开接管通道后，原行保留选择和焦点，直接配对仍可查询。重连后再次占用触发 Git 拒绝。解除占用后从零选显式提交，只删除 Linux 引用，通知更新为本次结果。 [断线](iteration-72-74-physical-en/i74-disconnected-branch-review.png) · [重连](iteration-72-74-physical-en/i74-reconnected-original-row.png) · [拒绝](iteration-72-74-physical-en/i74-refusal-and-retry.png) · [重试回执](iteration-72-74-physical-en/i74-explicit-retry-on-linux.png) |

试跑中，SSH 重置未激活原行重连。第一版修订恢复了重连和 Git 重试，成功通知仍携带旧失败说明和入口。最终修订把通知更新纳入两端实际回放。 [首次中断记录](iteration-72-74-trial/ssh-reset-run.json) · [旧通知画面](iteration-72-74-trial/i74-explicit-retry-on-linux.png)

## 第 69–71 轮

Windows x64 的隐藏客户端验证配对恢复、SSH 设置入口和 WSL 停止后的恢复。实机 SSH/Git 使用登记的 Linux 工作站，回环配对使用同一台 Windows 上的两套 Porpita 进程与档案。测试发行版和 Linux 上的 Git 夹具已清理。 [实机 SSH](iteration-69-71-physical-ssh/physical-ssh-checks.json) · [配对运行](iteration-69-71-paired-en/run.json) · [WSL 运行](iteration-69-71-wsl-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 69 | 920×700 英语界面完成五步。旧配对请求保持断线，从原行启动重连。Git 一时找不到引用时保留暂停，获得新结果后显式提交。独立 SSH 在两台实机的仓库比对同名同 HEAD 分支，并读到移动后的 Linux 路径。 [断线画面](iteration-69-71-paired-en/i67-paired-host-offline.png) · [断言](iteration-69-71-paired-en/paired-branch-checks.json) |
| 70 | 760×700 简中回放使用有独立 SSH 登记的隔离档案。打开原工作区操作、进入 SSH 设置。设置显示目标主机，工作区仍登记。物理 Git 夹具中的两条引用在界面操作后保持。 [工作区确认](iteration-69-71-ssh-zh/i70-ssh-project-needs-host-service.png) · [设置](iteration-69-71-ssh-zh/i70-ssh-settings-with-workspace-preserved.png) |
| 71 | 760×700 简中 Space 在真实 WSL 2 夹具完成十步。发行版在普通核对后保持停止，原行显式启动后出现新 Git 读数。再次占用仍由 Git 拒绝，释放后显式删除一条分支。 [停止](iteration-69-71-wsl-zh/i71-space-wsl-stopped.jpg) · [启动](iteration-69-71-wsl-zh/i71-space-wsl-started.jpg) · [断言](iteration-69-71-wsl-zh/space-branch-review-checks.json) |

第 69–71 轮已确认 Linux 主机的 OpenSSH 和 Git 可用。接续轮次部署同版本原生运行端并使用隔离项目保留实际 Host 和 Git 结果。 [第 69 轮范围](../ITERATION_69.md) · [同版本产物](../SOURCE_BASELINE.md#第-7274-轮来源)

首轮 SSH 设置的窄窗标题受到工具栏挤压。当前 Renderer 验证 760px 下工具栏换行，1160px 下同排，入口与登记保持。 [首轮窄窗](iteration-69-71-ssh-zh/i70-ssh-settings-with-workspace-preserved.png) · [当前窄窗](iteration-69-71-ssh-layout-zh/i70-ssh-settings-with-workspace-preserved.png) · [当前宽窗](iteration-69-71-ssh-layout-zh/i70-ssh-settings-wide.png)

## 第 66–68 轮

回环配对使用同一台 Windows 的两个 Porpita 进程和两套一次性仓库。英语浅色 920×700 与简中深色 760×700 各完成五步。主机断开与恢复走实际配对接口，Git 引用与工作树在测试仓库中真实变化。 [英语回放](iteration-66-68-paired-en/run.json) · [简中回放](iteration-66-68-paired-zh/run.json)

两种语言由档案设置和实际控件文字核对。主工作台的 HTML `lang` 在两次回放均为空，Space 的简中根节点记录为 `zh`。工作台语言标记和系统读屏登记在 M.02.26。 [英语控件记录](iteration-66-68-paired-en/i66-paired-host-checkout.json) · [简中控件记录](iteration-66-68-paired-zh/i66-paired-host-checkout.json)

| 轮次 | 实际结果 |
| --- | --- |
| 66 | 从工作台的保留分支通知进入复核。核对返回 Studio 的当前路径，原主机与本机的同名同 HEAD 引用保留。 [英语检出](iteration-66-68-paired-en/i66-paired-host-checkout.png) · [简中检出](iteration-66-68-paired-zh/i66-paired-host-checkout.json) |
| 67 | 断开时保留上次路径与勾选，提交暂停。恢复同一配对后在原行核对。再次占用触发 Git 拒绝，新复核从零选开始。解除占用并提交只删除 Studio 分支。 [断线](iteration-66-68-paired-en/i67-paired-host-offline.png) · [恢复](iteration-66-68-paired-zh/i67-paired-host-recovered.json) · [提交回执](iteration-66-68-paired-en/i67-paired-host-result.png) |
| 68 | Ubuntu WSL 2 在 Linux 文件系统的临时仓库完成八步。Space 在 760×700 简中深色窗显示发行版，移动路径保留大小写、空格和中文。已验证打开登记工作树、解除占用、再次占用及显式重试。 [WSL 路径](iteration-66-68-wsl-zh/i63-space-checkout-current.jpg) · [WSL 回执](iteration-66-68-wsl-zh/i65-space-checkout-retry-resolved.jpg) |

首轮回放发现配对断线错误类型及 WSL 工作树记录匹配的两个缺口。最终回放记录实际读取、选择与 Git 拒绝。 [首轮配对](iteration-66-68-trial/paired-first-run.json) · [首轮 WSL](iteration-66-68-trial/wsl-first-run.json) · [WSL 回放](iteration-66-68-wsl-zh/run.json) · [WSL 断言](iteration-66-68-wsl-zh/space-branch-review-checks.json)

Windows 本机 Git 路径另用英语复跑第 63–65 轮八步，核对原焦点与释放后的显式提交。 [本机回归](iteration-66-68-paired-en/regression-local-run.json) · [本机断言](iteration-66-68-paired-en/regression-local-checks.json)

改为按需加载远端保留通知后，在当前 Renderer 重新完成英语配对五步。 [当前回放](iteration-66-68-paired-head-en/run.json) · [当前断言](iteration-66-68-paired-head-en/paired-branch-checks.json) · [源码与构建](../SOURCE_BASELINE.md#第-6668-轮来源)

## 第 63–65 轮

Windows 隐藏客户端在英语浅色和简中深色各回放八步，Space 复核视口分别为 850×700 与 760×700。每次用真实 Git 和独立临时仓库，先实际移动关联工作树，再从主工作台返回同一复核。 [构建与范围](../SOURCE_BASELINE.md#第-6365-轮来源) · [英语回放](iteration-63-65-space-en/run.json) · [简中回放](iteration-63-65-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 63 | 按 Enter 核对已移动的检出。同一行显示新路径，勾选、焦点和两条分支的引用保留。 [英语当前路径](iteration-63-65-space-en/i63-space-checkout-current.jpg) · [简中当前路径](iteration-63-65-space-zh/i63-space-checkout-current.jpg) |
| 64 | 工作树切换分支后，核对显示未检出。英语另推进另一条分支的 HEAD，验证只撤下该项勾选且焦点可见。简中另临时重命名分支，验证查不到引用时保留上次路径和勾选，恢复后可重新核对。 [简中未检出](iteration-63-65-space-zh/i64-space-checkout-available.jpg) · [英语 HEAD 变化](iteration-63-65-space-en/i64-space-checkout-head-changed.jpg) · [简中结果未确认](iteration-63-65-space-zh/i64-space-checkout-unconfirmed.jpg) |
| 65 | 核对后实际再次占用。提交被拒绝，两条引用保留，新复核零选。解除占用后重新勾选并提交，Git 仅删除目标分支。 [再次占用](iteration-63-65-space-zh/i65-space-checkout-occupied-again.jpg) · [清理完成](iteration-63-65-space-zh/i65-space-checkout-retry-resolved.jpg) |

英语首轮在 HEAD 变化后发现焦点环被列表下缘部分遮住。第二次回放增加控件矩形断言，并核对滚动定位后的画面。 [首轮画面](iteration-63-65-space-trial/i64-focus-before-scroll.jpg) · [英语断言](iteration-63-65-space-en/space-branch-review-checks.json) · [简中断言](iteration-63-65-space-zh/space-branch-review-checks.json)

英语另回归第 60–62 轮的七步。直接提交时，旧检出实例的打开动作仍失效，Git 报告移动后的路径，解除占用后可显式重试。 [回归程序记录](iteration-63-65-space-en/regression-60-62-run.json) · [断言](iteration-63-65-space-en/regression-60-62-checks.json)

## 第 60–62 轮

Windows 隐藏客户端在英语浅色和简中深色各通过七步，Space 复核分别在 850×700 与 760×700 查看。使用一次性仓库和真实 Git 工作树移动，通过应用刷新工作树目录后执行返回。 [构建与范围](../SOURCE_BASELINE.md#第-6062-轮来源) · [英语回放](iteration-60-62-space-en/run.json) · [简中回放](iteration-60-62-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 60 | 原打开按钮消失后从主工作台返回同一 Space，焦点回到「取消」。分支选项与返回前主工作台活动工作树保留。 [基线](iteration-60-62-space-baseline/i60-space-checkout-drift-baseline.jpg) · [简中回退](iteration-60-62-space-zh/i60-space-fallback-focus.jpg) |
| 61 | 复核行标明「上次检出路径」并提示核对。英语另在同一路径登记 ID 相同、实例不同的工作树，核对旧打开动作仍不可用。 [英语状态](iteration-60-62-space-en/i61-space-last-checkout-path.jpg) · [简中状态](iteration-60-62-space-zh/i61-space-last-checkout-path.jpg) |
| 62 | Git 拒绝删除仍被检出的分支，复核显示移动后的新路径。实际释放占用后重新勾选提交，目标分支删除，另一条仍在。 [新路径](iteration-60-62-space-zh/i62-space-checkout-refreshed.jpg) · [清理完成](iteration-60-62-space-zh/i62-space-checkout-resolved.jpg) |

回放先切离临时工作树并等待应用完成终端关闭。两次提交均检查保留的 Git 引用。英语额外通过原按钮可用时的第 57–59 轮正常返程。 [英语断言](iteration-60-62-space-en/space-branch-review-checks.json) · [简中断言](iteration-60-62-space-zh/space-branch-review-checks.json) · [正常返程](iteration-60-62-space-en/regression-57-59-checks.json)

## 第 57–59 轮

Windows 隐藏客户端在英语浅色和简中深色各通过七步。回放沿用已登记与外部临时 worktree，主工作台分别为 1100×700 和 820×700。Space 对话框分别在 850×700 与 760×700 查看。 [构建与范围](../SOURCE_BASELINE.md#第-5759-轮来源) · [英语回放](iteration-57-59-space-en/run.json) · [简中回放](iteration-57-59-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 57 | 从 Space 打开登记工作树后，主窗状态栏出现明确的返回动作。缩窄后入口与当前工作树可见。 [英语状态栏](iteration-57-59-space-en/i57-workbench-return-entry.png) · [简中窄窗](iteration-57-59-space-zh/i57-workbench-return-entry.png) |
| 58 | 用 Enter 回到同一 Space，焦点回到刚使用的打开工作树按钮。已选与未选分支仍分明。 [英语回焦](iteration-57-59-space-en/i58-space-review-returned.jpg) · [简中回焦](iteration-57-59-space-zh/i58-space-review-returned.jpg) |
| 59 | 取消与关窗均撤下入口。简中另在这次复核仍活动时重载 Space 观察回收，旧请求失效。 [英语关闭态](iteration-57-59-space-en/i59-space-return-lifetime.png) · [简中关闭态](iteration-57-59-space-zh/i59-space-return-lifetime.png) |

回放在隐藏窗口中检查应用内焦点、窗口身份与 Git 引用。重载项取简中结果。 [英语断言](iteration-57-59-space-en/space-branch-review-checks.json) · [简中断言](iteration-57-59-space-zh/space-branch-review-checks.json)

## 第 54–56 轮

Windows 隐藏客户端中，英语浅色和简中深色各用五步回放，从前两步的工作树清理回到 Git 分支。登记工作树和外部 checkout 都在一次性仓库中创建，Space 使用 850×700 和 760×700 两种内容视口。 [构建与范围](../SOURCE_BASELINE.md#第-5456-轮来源) · [英语回放](iteration-54-56-space-en/run.json) · [简中回放](iteration-54-56-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 54 | Git 真实拒绝两条分支。登记项的路径和外部 checkout 的路径均与磁盘位置一致，外部路径含空格和中文。 [登记路径](iteration-54-56-space-zh/i54-space-checkout-paths.jpg) · [外部路径](iteration-54-56-space-zh/i54-space-checkout-external.jpg) |
| 55 | 从原 Dialog 打开正确工作树，确认主窗口活跃实例和 Host。原复核与勾选仍在，过期实例的协议请求被拒绝。 [主窗口](iteration-54-56-space-en/i55-branch-open-checkout.png) · [复核回执](iteration-54-56-space-zh/i55-space-checkout-opened.jpg) |
| 56 | 释放两个真实检出后各自重试。一项成功后另一项与入口仍在，最后一项提交后恢复筛选焦点。 [一次成功](iteration-54-56-space-zh/i56-space-checkout-resumed.jpg) · [复核结束](iteration-54-56-space-zh/i56-space-checkout-completed.jpg) |

首版的动作按钮和长路径分列，导致部分目录名换行较早。最终路径独占一行，列表沿用既有滚动。 [首版路径](iteration-54-56-space-trial/i54-checkout-path-trial.jpg) · [英语断言](iteration-54-56-space-en/space-branch-review-checks.json) · [简中断言](iteration-54-56-space-zh/space-branch-review-checks.json)

## 第 51–53 轮

Windows 隐藏客户端中，英语浅色在 850×700、简中深色在 760×700 验证了三条分支的混合结果、原因和恢复。两份回放各五步，前两步复验 Space 的行内拒绝及保留分支来源。Git 工作树、分支和提交都在一次性档案与临时仓库中建立。 [构建与范围](../SOURCE_BASELINE.md#第-5153-轮来源) · [英语回放](iteration-51-53-space-en/run.json) · [简中回放](iteration-51-53-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 51 | 同一批实际删除一条分支，另两条回到复核。切换筛选后仍可读本次结果。 [窄窗结果栏](iteration-51-53-space-zh/i51-space-branch-batch-result.jpg) |
| 52 | 一个分支已指向新提交，另一个已在新检出的工作树中使用。重开复核比较两个提交，键盘全选只涵盖当时可重试的条目。 [待复核状态](iteration-51-53-space-zh/i52-space-branch-refusals.jpg) |
| 53 | 英语先保留已变化分支，焦点留在复核并随后重新打开。简中先确认重试，再对最后一条选「保留分支」。结束后焦点和结果回到筛选，Git 仍持有变更分支。 [窗口内回焦](iteration-51-53-space-en/i53-space-branch-keep.jpg) · [复核结束](iteration-51-53-space-zh/i53-space-branch-recovered.jpg) |

旧版通知含技术错误，重开时两行仍可选。集成首版复核把已变化行的分支与提交文字压淡，最终沿用原字号与对比度来保留可读信息。 [旧版通知](iteration-51-53-space-baseline/i51-old-branch-refusal-toast.jpg) · [旧版选择](iteration-51-53-space-baseline/i52-old-branch-refusal-review.jpg) · [文字试验](iteration-51-53-space-baseline/i52-branch-opacity-trial.jpg) · [英语断言](iteration-51-53-space-en/space-branch-review-checks.json) · [简中断言](iteration-51-53-space-zh/space-branch-review-checks.json)

## 第 48–50 轮

英语浅色与简中深色各通过三个步骤。播放使用隐藏的 Windows Space 窗口、一次性 Porpita 档案及应用创建的托管工作树。失败行实测视口为 760×700，分支结果和复核为 1100×700。 [构建与范围](../SOURCE_BASELINE.md#第-4850-轮来源) · [英语回放](iteration-48-50-space-en/run.json) · [简中回放](iteration-48-50-space-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 48 | 审阅打开后写入新文件。普通删除失败，主窗口再次发布及通知关闭后，工作树行仍显示未提交的改动。 [简中窄窗](iteration-48-50-space-zh/i48-space-refusal-reason.jpg) |
| 49 | 两个工作树目录实际移除，分支 HEAD 仍为各自原值。筛选切到主工作树后，结果栏继续显示两个保留的 Git 分支及复核入口。 [结果栏](iteration-48-50-space-zh/i49-space-kept-branches.jpg) |
| 50 | 初始零选并聚焦取消。键盘全选、清空、Esc 后返回原入口。重开后提交一项，用实际 Git ref 验证另一项保持原 HEAD，入口里仍可复核它。 [零选](iteration-48-50-space-zh/i50-space-branch-review-empty.jpg) · [单选](iteration-48-50-space-zh/i50-space-branch-review-selected.jpg) · [回执](iteration-48-50-space-zh/i50-space-branch-review-result.jpg) |

首版的禁用提交按钮包含计数零。复验采用普通禁用标签，选择后再显示实际删除范围。 [首版](iteration-48-50-space-en/i50-space-zero-count-trial.jpg) · [英语断言](iteration-48-50-space-en/space-branch-review-checks.json) · [简中断言](iteration-48-50-space-zh/space-branch-review-checks.json)

## 第 45–47 轮

英语浅色与简中深色各通过 11 个隐藏 Windows 客户端步骤。Space 使用 1100×700 的实际独立渲染窗口。工作树创建、扫描、删除和 Git 拒绝都走 Porpita；工作树位于隔离临时目录。 [构建与范围](../SOURCE_BASELINE.md#第-4547-轮来源) · [英语回放](iteration-45-47-space-cleanup/run.json) · [简中回放](iteration-45-47-space-cleanup-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 45 | 真实审阅初始聚焦取消。Enter 和 Esc 均返回审阅入口，搜索词与选项保留。 [初始焦点](iteration-45-47-space-cleanup-zh/i45-space-review-cancel-focus.jpg) · [取消返回](iteration-45-47-space-cleanup-zh/i45-space-review-returned.jpg) |
| 46 | 实际移除一个临时工作树，显示一项完成，搜索框保留原筛选和焦点，另一项选择可恢复查看。 [单项完成](iteration-45-47-space-cleanup-zh/i46-space-cleaned.jpg) |
| 47 | 普通删除保留有临时修改的工作树，Space 显示部分结果。主窗口再次发布后失败原因仍留在对应行。移除测试文件并刷新后重新审阅和删除。 [部分结果](iteration-45-47-space-cleanup-zh/i47-space-partial.jpg) · [重试结果](iteration-45-47-space-cleanup-zh/i47-space-retried.jpg) |

首版截图显示主窗口同步后失败标记被覆盖。最终回放触发一次真实主窗口发布，再检查失败标记和行内原因。 [首版实况](iteration-45-47-space-cleanup/i47-space-overwritten-trial.jpg) · [英语断言](iteration-45-47-space-cleanup/workspace-ports-continuity-checks.json) · [简中断言](iteration-45-47-space-cleanup-zh/workspace-ports-continuity-checks.json)

## 第 42–44 轮

Windows 开发预览分别使用英语浅色与简中深色，各完成 8 个回放步骤。简中 PTY 为 600×460，开启减少动态。独立 Space 为 1100×700。状态与键盘断言取自实际界面，PTY 诊断入口使用仓库可见性夹具。 [构建与范围](../SOURCE_BASELINE.md#第-4244-轮来源) · [英语回放](iteration-42-44-resource-selection/run.json) · [简中回放](iteration-42-44-resource-selection-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 42 | 两个原分屏的 PTY 经过未选、部分选中、全选和清空，核对结束计数和可访问名称。 [简中窄窗](iteration-42-44-resource-selection-zh/i42-pty-eligible-selection.png) · [选择轨迹](iteration-42-44-resource-selection-zh/pty-eligible-selection/timeline.json) |
| 43 | 图块与标题按钮分别进入真实目录图，返回后焦点回到概览。 [目录图](iteration-42-44-resource-selection-zh/i43-space-folders.jpg) · [概览及焦点](iteration-42-44-resource-selection-zh/i43-space-overview.jpg) |
| 44 | 选择两个已托管工作树，筛选后审阅唯一可见目标并取消。全隐藏时审阅不可用，清除筛选后恢复两项。 [一项可见](iteration-42-44-resource-selection-zh/i44-space-filtered.jpg) · [审阅目标](iteration-42-44-resource-selection-zh/i44-space-one-target-review.jpg) · [全隐藏](iteration-42-44-resource-selection-zh/i44-space-hidden-only.jpg) |

首轮验证使用 Git 创建的临时链接工作树。Space 显示「未托管」，选择不可用。后续改用 Porpita 创建的临时工作树验证可选情形，主工作树保护继续按实际状态检查。 [未托管实况](iteration-42-44-resource-selection/i44-space-unmanaged-trial.jpg) · [英语断言](iteration-42-44-resource-selection/workspace-ports-continuity-checks.json) · [简中断言](iteration-42-44-resource-selection-zh/workspace-ports-continuity-checks.json)

## 第 39–41 轮

Windows 开发预览分别使用英语浅色和简中深色。简中回放在 600×460 开启减少动态检查本机 PTY 和 Space 入口。资源行显示真实本机 PTY，诊断入口使用仓库可见性夹具。磁盘结果来自实际工作树扫描，Space 子窗口保持隐藏。 [构建与范围](../SOURCE_BASELINE.md#第-3941-轮来源) · [英语回放](iteration-39-41-resource-continuity/run.json) · [简中回放](iteration-39-41-resource-continuity-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 39 | 从 Resources 和本机 PTY 切到同一标签内的两个原窗格。对照排序编号、PTY 身份和当前键盘焦点。 [终端回源连续帧](iteration-39-41-resource-continuity/resource-to-original-terminal/timeline.json) |
| 40 | 使用实际无标签进程和两条已绑定 PTY。诊断读取失败时保留列表，重试后恢复定位。 [英语失败画面](iteration-39-41-resource-continuity/local-pty-availability/019.jpg) · [简中窄窗](iteration-39-41-resource-continuity-zh/i40-pty-availability.png) |
| 41 | 扫描后发出 Space 请求，受控失败留在原面板。重试用实际独立窗口显示扫描，关闭后继续同一 Explorer。 [连续回放](iteration-39-41-resource-continuity/resources-to-space/timeline.json) · [Space 实况](iteration-39-41-resource-continuity/i41-space-window.jpg) |

原生焦点和采样在各自环境验收。本组断言记录 renderer 焦点、既有进程身份、真实扫描和窗口状态。 [英语断言](iteration-39-41-resource-continuity/workspace-ports-continuity-checks.json) · [简中断言](iteration-39-41-resource-continuity-zh/workspace-ports-continuity-checks.json)

同一构建复查第 37 轮的监听热替换及 Browser 打开。 [端口复验](iteration-39-41-port-regression/run.json) · [刷新和选择](iteration-39-41-port-regression/refresh-stale-listener/timeline.json)

## 第 36–38 轮

Windows 开发预览使用一次性本机和 Studio 档案。常规画面为 1280×800，英语采用浅色，简中采用深色。简中详情还在 600×460 核对。每项证据保有触发、画面和回放断言。两边的服务都在同一台机器上。 [构建身份](../SOURCE_BASELINE.md#第-3638-轮来源) · [英语回放](iteration-36-38-port-targets/run.json) · [简中回放](iteration-36-38-port-targets-zh/run.json)

| 轮次 | 实际结果 |
| --- | --- |
| 36 | 本机的监听和浏览器地址各有字段，Studio 详情显示来源。简中详情值使用可读文案。 [窄窗本机详情](iteration-36-38-port-targets-zh/port-address-provenance/099.jpg) · [详情连续帧](iteration-36-38-port-targets-zh/port-address-provenance/timeline.json) · [窄窗 Studio 详情](iteration-36-38-port-targets-zh/i36-port-address.png) |
| 37 | 保留预览并刷新原端口列表，等明确选择替换后的监听才打开真实环回 HTML。 [刷新与回焦](iteration-36-38-port-targets-zh/refresh-stale-listener/timeline.json) · [本机 Browser](iteration-36-38-port-targets/i37-port-refresh.png) |
| 38 | 从 Studio 的资源表选择本机 Browser 行，核对标签、页面和数量，返回原 Explorer。 [资源表 Browser 行](iteration-36-38-port-targets/resources-to-existing-browser/016.jpg) · [定位到同一页面](iteration-36-38-port-targets/resources-to-existing-browser/024.jpg) · [简中连续帧](iteration-36-38-port-targets-zh/resources-to-existing-browser/timeline.json) |

资源树的指标来自样本。资源树可见后，端口、Browser 和工作树导航均通过真实控件。窗口保持隐藏，前台实时采样和其他设备各需自己的验证。 [英语断言](iteration-36-38-port-targets/workspace-ports-continuity-checks.json) · [简中断言](iteration-36-38-port-targets-zh/workspace-ports-continuity-checks.json)

## 第 33–35 轮

Windows 隐藏回放的英语浅色与简中深色各完成 10 步。端口使用实际环回监听，应用内 Browser 加载测试工作树提供的 HTML。简中详情在 600×460 检查。资源工作树行使用样本与仓库的渲染器可见性夹具，定位和返回是实际操作。 [构建身份](../SOURCE_BASELINE.md#第-3335-轮来源) · [英语](iteration-33-35-port-resources/run.json) · [简中](iteration-33-35-port-resources-zh/run.json)

| 轮次 | 可核对的证据 |
| --- | --- |
| 33 | [详情归属连续帧](iteration-33-35-port-resources/port-detail-origin/timeline.json) · [窄窗详情](iteration-33-35-port-resources-zh/i33-port-details.png) |
| 34 | [替换监听和浏览器打开](iteration-33-35-port-resources-zh/port-to-browser/timeline.json) · [实际环回页面](iteration-33-35-port-resources/i34-port-browser.png) |
| 35 | [资源定位与返回](iteration-33-35-port-resources-zh/resource-to-native-worktree/timeline.json) · [回到同一 Studio Explorer](iteration-33-35-port-resources/i35-resource-worktree.png) |

采样门槛未作为本轮前台验证。资源行通过夹具可见后，测试点击的是真实工作树定位按钮，并已检查切换到预期 Host。 [英文断言](iteration-33-35-port-resources/workspace-ports-continuity-checks.json) · [简中断言](iteration-33-35-port-resources-zh/workspace-ports-continuity-checks.json)

## 第 30–32 轮

Windows 隐藏回放从两个实际工作树打开固定 Explorer，两个隔离 Runtime 各读所属目录的真实环回监听。英语浅色和简中深色各完成 7 步。资源画面验证本机范围和 PTY 标签，数字采用明确的布局样本。首轮另保留同一 Workspace 内两条 Chat 切换端口来源的证据。 [构建身份](../SOURCE_BASELINE.md#第-3032-轮来源) · [英语浅色](iteration-30-32-ports/run.json) · [简中深色](iteration-30-32-ports-zh/run.json)

| 轮次 | 可核对的证据 |
| --- | --- |
| 30 | [混合 Chat 首轮](iteration-30-32-mixed-trial/ports-scope-handoff/timeline.json) · [最终工作树端口](iteration-30-32-ports-zh/i30-ports-scope.png) · [回源继续](iteration-30-32-ports/ports-to-native-worktree/timeline.json) |
| 31 | [断线时切到本机](iteration-30-32-ports-zh/ports-host-outage/timeline.json) · [重连读取替换端口](iteration-30-32-ports-zh/i31-ports-recovery.png) · [撤回配对](iteration-30-32-ports-zh/i31-ports-revoked.png) |
| 32 | [两个 Host 上的本机范围](iteration-30-32-ports/local-resource-scope/timeline.json) · [600×460 资源样本](iteration-30-32-ports-zh/i32-resource-scope.png) |

全旅程曾停在 Vault 测试历史的索引阶段，最终改用固定 Explorer 验证本轮范围。初次重连复验中端口弹层随连接状态切换收起，后续等待 Studio Explorer 文件列表恢复后再打开。现有原生可见性门槛在两组回放中保持启用。 [英文断言](iteration-30-32-ports/workspace-ports-continuity-checks.json) · [简中断言](iteration-30-32-ports-zh/workspace-ports-continuity-checks.json)

## 第 27–29 轮

Windows x64 开发预览使用同一台机器上的两个隔离 Runtime。英语浅色与简中深色各完成 21 步。账户设置、原编辑器和断线回放使用实际客户端操作。37% 用量仅为窄窗呈现夹具。 [构建身份](../SOURCE_BASELINE.md#第-2729-轮来源) · [英语浅色](iteration-27-29-usage/run.json) · [简中深色](iteration-27-29-usage-zh/run.json)

| 轮次 | 可核对的证据 |
| --- | --- |
| 27 | [同名 Chat 用量切换](iteration-27-29-usage/usage-follows-chat/timeline.json) · [本机 Chat 与 Studio Explorer 同屏](iteration-27-29-usage-zh/i25-narrow-workspace.png) |
| 28 | [账户交接连续帧](iteration-27-29-usage-zh/usage-accounts-handoff/timeline.json) · [同一 Host 的用量标题和读数夹具](iteration-27-29-usage-zh/i28-populated-usage.png) · [Studio 编辑器](iteration-27-29-usage/i24-open-original-studio.png) |
| 29 | [离线画面](iteration-27-29-usage-zh/explorer-source-outage/017.jpg) · [重连用量](iteration-27-29-usage-zh/usage-after-reconnect/timeline.json) · [撤回配对](iteration-27-29-usage-zh/i26-explorer-revoked.png) |

同一 Host ID 配对变化的聚焦测试使用了不同的配额值和迟到的刷新，验证旧读数不会替换新配对。实际提供方额度、登录及账户切换待有授权的环境。 [英文回放断言](iteration-27-29-usage/workspace-explorer-continuity-checks.json) · [简中回放断言](iteration-27-29-usage-zh/workspace-explorer-continuity-checks.json)

## 第 24–26 轮

Windows x64 后台 Electron 中使用两个隔离 Runtime 和同机回环配对。两份 Git 夹具目录名称与标记文件路径相同，文件内容不同。真实文件读取和编辑器回源在应用内通过，Codex 历史和未发送草稿由夹具提供。共归档 57 步，英语浅色与简中深色各 17 步，本机旧档案与工作空间回归 23 步。 [构建身份](../SOURCE_BASELINE.md#第-2426-轮来源) · [英语浅色](iteration-24-26-loopback/run.json) · [简中深色](iteration-24-26-loopback-zh/run.json) · [本机旧档案](iteration-26-local-profile/run.json)

| 轮次 | 可核对的证据 |
| --- | --- |
| 24 | [按 Host 选择目录](iteration-24-26-loopback-zh/i24-source-picker.png) · [源目录与键盘选择](iteration-24-26-loopback-zh/explorer-scope-selection/timeline.json) · [本机文件](iteration-24-26-loopback-zh/i24-open-original-local.png) · [Studio 文件](iteration-24-26-loopback-zh/i24-open-original-studio.png) |
| 25 | [同实例移动及滚动](iteration-24-26-loopback-zh/explorer-placement-and-scroll/timeline.json) · [600×460 实际画面](iteration-24-26-loopback-zh/i25-narrow-workspace.png) · [回到两份筛选](iteration-24-26-loopback-zh/i25-two-instance-return.json) |
| 26 | [重启恢复](iteration-24-26-loopback-zh/i26-cold-explorer.png) · [单侧停机](iteration-24-26-loopback-zh/explorer-source-outage/timeline.json) · [重连到原目录](iteration-24-26-loopback-zh/explorer-source-recovery/timeline.json) · [撤回配对](iteration-24-26-loopback-zh/i26-explorer-revoked.png) · [移除及焦点断言](iteration-24-26-loopback-zh/workspace-explorer-continuity-checks.json) |

回放通过真实窗口的目录选择器、Explorer 位置菜单和远程设置完成。首次英文冷启动曾出现原生快捷键提示，复现工具通过可见的「Got it／知道了」处理。英文从 Explorer 手动重连，简中在同一个 Runtime 启动后自动恢复。连续帧用于核对操作、响应顺序和焦点。 [英文断言](iteration-24-26-loopback/workspace-explorer-continuity-checks.json) · [简中断言](iteration-24-26-loopback-zh/workspace-explorer-continuity-checks.json)

## 第 21–23 轮

Windows Electron 通过后台窗口执行，共 49 步。英语浅色与简中深色的混合 Workspace 回放各 13 步，另有本机工作空间和旧档案回归 23 步。流程使用同机两个隔离 Runtime、合成的 Codex 历史及未发送草稿。 [构建与复现](../SOURCE_BASELINE.md#第-2123-轮来源) · [英语回放](iteration-21-23-loopback/run.json) · [简中回放](iteration-21-23-loopback-zh/run.json) · [本机档案回放](iteration-22-local-profile/run.json)

| 轮次 | 可核对的证据 |
| --- | --- |
| 21 | [简中同名双 Pane](iteration-21-23-loopback-zh/i21-mixed-workspace.png) · [组合连续帧](iteration-21-23-loopback/workspace-host-composition/timeline.json) · [目录回原 Pane](iteration-21-23-loopback/i21-reopen-from-directory.json) · [600×460 切换过程](iteration-21-23-loopback-zh/workspace-host-short-switch/timeline.json) |
| 22 | [v2 保存](iteration-21-23-loopback/i22-save-qualified-layout.json) · [真实客户端重启](iteration-21-23-loopback-zh/i22-cold-mixed-restore.png) · [v1 读取和编辑保存](iteration-22-local-profile/i22-v1-profile.json) |
| 23 | [单侧断线与本机编辑](iteration-21-23-loopback-zh/i23-studio-outage.png) · [原 Pane 重连连续帧](iteration-21-23-loopback/workspace-host-recovery/timeline.json) · [撤回配对](iteration-21-23-loopback-zh/i23-pairing-removed.png) · [移除后的输入焦点](iteration-21-23-loopback/i23-remove-stale-reference.json) |

初步回放曾只返回本机匹配。最终用应用的重命名操作给两条 Chat 同名标题，并在目录确认 Studio 来源后进入选择器。启动前缀、选择步骤和可用状态记录在正式回放。冷启动用两次客户端进程与同一个仍运行的 Studio Runtime 核对边界。CDP 采样用于顺序、画面与焦点，物理设备及真实账号操作分别验收。 [初始选择器](iteration-21-23-shape/i21-picker-initial.jpg) · [首个双 Pane 画面](iteration-21-23-shape/i21-two-hosts-first.png) · [来源断言](iteration-21-23-loopback/workspace-host-continuity-checks.json)

## 第十八至二十轮

最终源码的 Windows 预览分别以英语浅色与简中深色回放。第十八轮每种语言 16 步，含现有目录回归。第十九轮每种语言 4 步，以本地协议 Harness 驱动真实原生 Chat 和审批提示。第二十轮每种语言 9 步，用同一机器上的两个独立 Runtime 检查实际跨 Host 来源、断线和重连。默认构建另完成 1 步预览隔离和 11 步 Vault 回归。 [构建身份](../SOURCE_BASELINE.md#第十八至二十轮来源)

| 轮次 | 可核对的证据 |
| --- | --- |
| 18 | [简中窄窗](iteration-18-windows-zh/i18-history-mode.png) · [恢复原历史连续帧](iteration-18-windows-zh/unopened-to-chat/timeline.json) · [断言](iteration-18-windows-zh/unopened-history-checks.json) · [英语回放](iteration-18-windows/run.json) · [简中回放](iteration-18-windows-zh/run.json) |
| 19 | [工作中](iteration-19-windows/i19-running.png) · [需要关注与实际提示](iteration-19-windows-zh/i19-needs-attention.png) · [状态连续帧](iteration-19-windows/running-to-attention/timeline.json) · [协作状态](iteration-19-windows-zh/i19-collaboration.png) · [英语回放](iteration-19-windows/run.json) · [简中回放](iteration-19-windows-zh/run.json) |
| 20 | [两个来源](iteration-20-loopback/i20-directory-hosts.png) · [暂时失联](iteration-20-loopback-zh/i20-directory-offline.png) · [实际重连连续帧](iteration-20-loopback/directory-host-reconnect/timeline.json) · [工作位置与草稿断言](iteration-20-loopback/session-index-host-checks.json) · [英语回放](iteration-20-loopback/run.json) · [简中回放](iteration-20-loopback-zh/run.json) |
| 默认 | [不启用目录预览的入口检查](iteration-18-20-default/run.json) · [原 Vault、终端与 /resume 回归](iteration-18-20-vault-regression/run.json) |

[初始短窗试验](iteration-18-20-shape/i18-history-mode.png) 和 [叠加扫描提示的中间画面](iteration-18-20-shape/i18-stacked-scan-notices.jpg) 用于说明结果区问题。最终回放以实际行菜单、焦点和原生对象匹配为准。合成历史与合成 Harness 事件的使用范围见对应 SPEC。CDP 时间序列用于核对状态、顺序和可见焦点。

## 第十五至十七轮

I1501–I1703 绑定 Porpita Windows x64 的显式预览。测试通过真实产品入口打开两个本地 Git 项目并建立三个 Native Chat。其中两条加入已有 Workspace，第三条继续在原 Worktree。历史使用一次性 Codex 记录，由 Vault 实际扫描和恢复。英语浅色和简中深色各通过 13 个步骤。默认构建另通过一个入口检查及 11 步 Vault 回归。 [英语](iteration-15-17-windows/run.json) · [简中](iteration-15-17-windows-zh/run.json) · [默认入口](iteration-15-17-default/run.json) · [Vault 回归](iteration-15-17-vault-regression/run.json) · [构建身份](../SOURCE_BASELINE.md#第十五至十七轮来源)

| 轮次 | 可核对的证据 |
| --- | --- |
| 15 | [空目录](iteration-15-17-windows/i15-empty.png) · [三条会话](iteration-15-17-windows/i15-directory.png) · [鼠标回 Worktree](iteration-15-17-windows/i15-native-target.json) · [键盘回 Workspace](iteration-15-17-windows/directory-to-workspace/timeline.json) |
| 16 | [短窗试验](iteration-15-17-shape/i16-scoped-projects.png) · [640×520 最终结果](iteration-15-17-windows-zh/i16-scoped-projects.png) · [600×400 导航滚动](iteration-15-17-windows-zh/i16-short-navigation.png) · [截图几何与菜单焦点](iteration-15-17-windows-zh/session-index-checks.json) |
| 17 | [Vault 接收查询](iteration-15-17-windows/i17-history-search.png) · [真实历史回原 Pane 连续帧](iteration-15-17-windows-zh/history-to-workspace/timeline.json) · [返回后目录状态](iteration-15-17-windows-zh/i17-return-directory.json) |

短窗试验来自开发预览的中间版本，用于比较可见列表空间。最终回放数据包含 CSS 尺寸、DPR、语言、主题、焦点和截图路径。连续帧核对交接前后的可见界面与 Composer 焦点。Windows CDP 后台采样用于观察状态，性能需单独量测。

## 第十二至十四轮

I1201–I1402 来自带 Workspace 预览开关的 Windows Electron 开发构建。本轮回放继续覆盖第九至十一轮，随后用相同测试档案运行旧记录导入、新进程恢复、读取失败重试、搜索焦点交接与 600px 拖放。档案在本机隔离，使用未登录的原生会话和真实合成项目文件。 [构建身份与运行](../SOURCE_BASELINE.md#第十二至十四轮来源)

英语浅色和简中深色各通过 22 步。其中每次含 11 步前轮回归。默认构建完成常规入口和 Vault 搜索回归，共 6 步。 [英语](iteration-12-14-windows/run.json) · [简中](iteration-12-14-windows-zh/run.json) · [默认入口](iteration-12-14-default/run.json) · [Vault](iteration-12-14-index-regression/run.json)

| 轮次 | 证据 |
| --- | --- |
| 12 | [保存](iteration-12-14-windows/i12-profile-save.json) · [迁移](iteration-12-14-windows/i12-legacy-migration.json) · [进程重启](iteration-12-14-windows/i12-cold-restore.json) · [读取失败及恢复](iteration-12-14-windows/i12-read-failure.json) |
| 13 | [目的地](iteration-12-14-windows/i13-location.png) · [焦点交接](iteration-12-14-windows/session-to-workspace/timeline.json) · [原 Worktree 路径](iteration-12-14-windows/i13-normal-fallback.json) |
| 14 | [拖放、取消与焦点](iteration-12-14-windows/group-move-cancel/timeline.json) · [确认后恢复原对象](iteration-12-14-windows/i14-move-to-group.json) |

## 第九至十一轮

I901–I1104 绑定显式启用预览开关的 Porpita Windows x64 开发构建。运行通过实际界面建立两个本地 Git 工作树与未登录 Codex Chat，在两个会话内输入各自草稿，切换尺寸、分组和 Explorer 宿主。文件读取及编辑器回源走实际运行路径。档案为一次性，后台窗口保持隐藏。 [来源与复现](../SOURCE_BASELINE.md#第九至十一轮来源)

英语浅色和简中深色各完成 11 个步骤。回放包含 1280×800、692×520、600×460 和 820×540 CSS px、DPR 1。缩窄阶段模拟减少动态。默认构建另检查入口和共享分隔线行为。 [英语回放](iteration-09-11-windows/run.json) · [简中回放](iteration-09-11-windows-zh/run.json) · [默认入口](iteration-09-11-default/run.json) · [Worktree 分屏复验](iteration-09-11-worktree-regression/run.json)

| 轮次 | 证据 |
| --- | --- |
| 09 | [真实双会话](iteration-09-11-windows/i9-two-worktrees.png) · [连续 Pane 切换](iteration-09-11-windows/workspace-pane-return/timeline.json) · [Pane 最小宽度](iteration-09-11-windows/pane-budget.json) · [再次打开](iteration-09-11-windows/i9-reopen.json) |
| 10 | [键鼠分组](iteration-09-11-windows/i10-groups.json) · [窄窗查找](iteration-09-11-windows/find-hidden-work/timeline.json) · [标题栏测量](iteration-09-11-windows/group-geometry.json) · [重载](iteration-09-11-windows/i10-layout-restore.json) |
| 11 | [嵌入](iteration-09-11-windows/i11-move-panel.png) · [移动过程](iteration-09-11-windows/explorer-placement/timeline.json) · [移回独立](iteration-09-11-windows/i11-detach.json) · [原编辑器](iteration-09-11-windows/i11-original-file.png) |

## 第六至八轮

I601–I805 包含两个变更前对照和最终 Windows 开发构建的六次回放。各次使用后台 Electron 和独立测试档案。英语浅色与简中深色覆盖常规窗口和 600/820 CSS px 窄窗，缩窄时模拟系统减少动态。会话历史使用合成 Codex 记录，Explorer 读取实际临时项目文件。每帧 JSON 记录尺寸、主题、焦点和实际图像文件。

| 轮次 | 验收内容 | 回放 |
| --- | --- | --- |
| 06 | 从跳转面板向会话历史转交标题、键盘焦点、窄窗及空词。Dock 不可用的 Skills 页保留跳转 | [基线](iteration-06-baseline/run.json) · [英语](iteration-06-windows/run.json) · [简中](iteration-06-windows-zh/run.json) · [交接连续帧](iteration-06-windows/query-to-history/timeline.json) |
| 07 | 实际两终端左右分屏、键盘限位、拖动期间按 Esc 回到 60% | [英语](iteration-07-windows/run.json) · [简中](iteration-07-windows-zh/run.json) · [撤销连续帧](iteration-07-windows-zh/cancel-split-resize/timeline.json) |
| 08 | 返回 Explorer 后恢复查询、两工作树分别恢复，并从原工作树打开真实文件 | [基线](iteration-08-baseline/run.json) · [英语](iteration-08-windows/run.json) · [简中](iteration-08-windows-zh/run.json) · [切换连续帧](iteration-08-windows/explorer-tool-return/timeline.json) |

使用现有回放入口 `node tools/observe-installed.cjs <证据目录> --related-index`、`--related-split` 或 `--related-explorer`。追加 `--related-baseline` 使用对应前置构建。完整对象状态与构建身份见 [覆盖矩阵](../COVERAGE_MATRIX.md) 和 [源码基线](../SOURCE_BASELINE.md)。

## 第五轮

I501–I510 包含第四轮对照与第五轮 Windows 回环配对。实际桌面和 serve 进程使用独立档案、项目和索引。两种语言各 9 个步骤，另保存重试与回到原 Chat 的连续帧。 [基线](iteration-05-baseline/run.json) · [英语](iteration-05-windows/run.json) · [简中](iteration-05-windows-zh/run.json) · [规范](../ITERATION_05.md)

## 第四轮

I401–I411 来自第三轮基线构建和第四轮 Windows 开发构建。用隔离的 Codex JSONL 记录验证真实客户端的历史扫描、搜索、重开和 `/resume`，原终端的会话身份由状态夹具供给。窗口在后台保持隐藏。英语浅色和简中深色各通过 11 步及两段焦点切换回放。 [基线](iteration-04-baseline/i4-history.png) · [英语回放](iteration-04-windows/run.json) · [简中回放](iteration-04-windows-zh/run.json) · [设计和限制](../ITERATION_04.md)

## 第三轮

I301–I308 使用第二轮基线及第三轮隔离 Windows 构建。两套相同本地 Git 测试项目里各有一个同名 Native Chat。未登录、草稿未发送，窗口保持后台隐藏。第三轮保存鼠标与键盘选择序列、原 Tab/Pane 和草稿验证结果。 [基线对照](iteration-03-baseline/i3-same-name.png) · [英语回放](iteration-03-windows/run.json) · [简中深色](iteration-03-windows-zh-final/run.json) · [连续事件](iteration-03-windows/continue-open-chat/timeline.json)

## 第二轮

| 证据 | 条件与结果 |
| --- | --- |
| I201–I203、I214 | Windows 开发构建的双终端和现有左右栏，600/820/1280 CSS px、顶部及侧置 Activity Bar。临时收起、焦点、Explorer 查询和放宽恢复均有测量。 [实际几何](iteration-02-windows/layout-measurements.json) · [回放](iteration-02-windows/run.json) |
| I204–I205 | 真实启动信任在 600×400 保持两个操作可达，Sonner 与通知卡片栈隐藏，Escape 不作选择，键盘完成「让智能体询问」。 [截图](iteration-02-windows/i2-trust-narrow.png) · [命中测试](iteration-02-windows/trust-measurement.json) |
| I206–I207 | 临时 Git 仓库从实际添加入口进入 Source Control；Porpita Help 含独立产品支持及交付入口。 [Source Control](iteration-02-windows/i2-project-scope.png) · [Help](iteration-02-windows/i2-help.png) |
| I208–I210 | Candidate 11 安装版两次从隔离档案启动、断开并恢复本机 Core。一次原 Settings 页恢复，另一次超过原页 10 秒观测窗口，重新打开后显示已连接。 [后一次结果](iteration-02-core/core-recovery-measurement.json) |
| I211–I213 | 组件 Shape 的实际键鼠：选择、恢复最近 Tab、溢出、拖放取消和移组。普通 Sheet 既有通知提升和关闭也通过夹具。 [操作记录](group-shape/interaction.json) · [浮层](group-shape/ui__sonner--olderToastBehindModalSheet.light.png) |
| I215–I216 | 从真实 Windows 工作台进入 Codex Native Chat 的未登录空态，缩至 600×400 后 Chat 319px、输入框 281px。 [回放](iteration-02-windows/i2-chat-narrow.png) · [测量](iteration-02-windows/chat-measurement.json) |
| I217–I218 | 在实际 folder 与 Git 工作树行之间切换，返回同一 Source Control；在 Codex Chat 用原分屏动作打开同 worktree 的终端。 [工作树](iteration-02-windows/i2-project-return.png) · [Chat 和终端](iteration-02-windows/i2-chat-terminal-split.png) |

复现入口为 `node tools/observe-installed.cjs <证据目录> --closeout`（隔离源码构建）和 `node tools/observe-installed.cjs <证据目录> --core-recovery`（Candidate 11 安装版）。源码和可执行文件环境变量沿用下文。Group Selector 复现见 [试验](../GROUP_TRIAL.md)。

## 首轮

**对象**：Porpita 0.1.0，Windows x64，已安装候选 11；身份见 [来源基线](../SOURCE_BASELINE.md)。使用 Playwright CDP 操作后台隐藏的 Electron renderer；默认测试尺寸 1280×800（CSS，DPR 1），另测 820×580、深色和模拟减少动态。档案为一次性隔离环境；部分 runs 使用合成仓库或预设向导完成状态。未把模型、服务、外部设备、插件市场或供应方账号的行为假定为已验证。具体条件见每帧同名 JSON、run manifest 和 [证据映射](observations.json)。

| 回放 | 已看或可定位的材料 | 能说明的事实 |
| --- | --- | --- |
| EV01–EV04 | [首用](02-onboarding.png) · [信任](episode/03-onboarding-skip.png) · [工作台](04-shell.png) · [协作未配置](05-collaboration-unconfigured.png) | 首用模式选择、可信确认、主工作区与 Dock、未连接状态；不验证全向导或消息服务 |
| EV05–EV11 / S01–S32 | [通用](06-settings.png) · [设置总览 1](settings-census/index-1.jpg) · [2](settings-census/index-2.jpg) · [3](settings-census/index-3.jpg) · [4](settings-census/index-4.jpg) · [回放记录](settings-census/run.json) | 实际点击 32 个常规可见分区并观察首屏，另补动态项目设置 EV46；独立子控件/条件状态仍待测 |
| EV12–EV17 / EV28–EV29 | [搜索](15-search.png) · [任务无项目来源](tools-extra/32-tasks-settled.png) · [自动化](17-automations.png) · [配对入口](18-mobile.png) · [工件](workbench/19d-artifacts.png) · [技能](workbench/19e-skills.png) · [Browser 新标签](tools-extra/33-browser-blank.png) | 正常入口、空/受限状态和导航。手机页和 Chat UI 教育卡的样例不是实时数据；Browser 未加载外部站点 |
| EV18–EV23 / EV25 | [打开 Markdown](local-tools/19b-editor.png) · [新建 Tab 菜单](local-tools/22-new-tab.png) · [终端分屏](local-tools/23-terminal-split.png) · [右栏关闭](local-tools/24-right-dock-closed.png) · [重开](local-tools/24b-right-dock-reopened.png) · [窄窗](local-tools/25-narrow.png) · [减少动态的终点](local-tools/26-reduced-dock.png) | 隔离文件被真实打开；既有终端左右分屏及 Dock 显隐。窗口缩小时内容受挤压，不证明目标方案已达成 |
| EV27 / EV30–EV32 | [窄窗安全确认](replay-b/25-narrow.png) · [添加项目](tools-extra/27-add-project.png) · [工作区创建](tools-extra/28-new-worktree.png) · [设置切换深色](episode/30-theme.png) | 真实打开相应界面；安全确认前的 toast 重叠是观察缺口。未提交创建、未对真实项目授权 |
| EV33–EV35 | [连续帧总览](episode/dock-episode/sequence.jpg) · [时间序列](episode/dock-episode/timeline.json) · [Activity 左栏](episode/35-activity.png) · [工作树看板](episode/36-board.png) | 62 个 CDP 采样帧：开→关→开→关，重开短暂加载 Explorer，最后关闭。设置和工作台深色；Activity 与看板是现有执行工作树视图。采样和自动化时间不作为自然节奏/性能 |

EV36–EV38：[临时 Git 主检出](git-intake/37-git-worktree.png) · [Git Changes](git-intake/38-git-changes.png) · [Monaco Diff](git-intake/39-git-diff.png)。后台回放只替代系统目录选择器的返回路径，Porpita 内的项目接入、检出激活和 Diff 均经真实控件；未提交或访问远端。该结果解决此前仅由 IPC 登记仓库无法稳定进入目标的回放路径。

EV39–EV40：[Agent 启动菜单](chat-start/41-chat-agent-menu.png) · [真实 Native Chat 首屏](chat-start/42-chat-empty.png)。隔离档案中开启 Chat UI，从新 Tab 选择 Codex，实际进入 Chat，见未登录提示、Pane 头、Composer 与权限/模型入口。未登录、未发送请求；当前证据不能证明流式或批准结果。

FX01–FX05：[当前源码组件预览](source-fixtures/) 使用 Porpita 内置 fixture renderer，含宽窄标签条、审批展开、等待输入、消息和连接提示。样例数据不是系统事实。冷启动一次报告资源 404；同组预览复验 12/12 输出且退出码为 0。TR01–TR03：[分组对照试验](../GROUP_TRIAL.md) 运行当前源码的原生标签条与菜单，未接入产品工作对象。

EV41–EV42：[Explorer 内容搜索结果](dock-panels/37a-content-search.png) · [Vault 扫描中](dock-panels/37b-vault.png)。使用同一临时 Git 仓库，看到实际命中行与 Agents 历史的范围切换/扫描。早期未命中 Checks 本地化名称；后续 EV45 已补证。Ports、folder 专属面板、第三方插件仍待按条件检查。

EV43–EV44：[重开时的功能提示](restart/51-after-restart.png) · [返回已恢复的文档](restart-recheck/52-resume-editor.png)。同一隔离档案正常退出（退出码 0 的复验），重开后恢复活动 Markdown，关闭教育提示后可继续。未由此证明后台 PTY 保活或 Porpita 目标 Workspace 的关闭/恢复语义。

EV45–EV46：[Checks 身份验证失败与重试](checks-project-settings/37c-checks.png) · [动态 Git 项目设置](checks-project-settings/39a-project-settings.png)。无实际 GitHub 凭据的临时档案，未触发重试或保存设置。

EV47–EV48：[独立 Space](auxiliary-en/53-space-window.png) · [独立 Agent Dashboard（简中）](auxiliary/54-dashboard-window.png) · [英文](auxiliary-en/54-dashboard-window.png)。通过实际状态栏/Sidebar 入口触发独立 renderer，均核对隐藏。未扫描磁盘、清理或激活桌面窗口。

SRC01–SRC06：[HEAD 首用](current-source/02-onboarding.png) · [HEAD 深色](current-source/30-theme.png) · [HEAD 看板](current-source/36-board.png) · [HEAD 未配置协作](current-connections/44-source-collaboration.png) · [HEAD 通用](current-connections/45-source-general.png) · [HEAD 手机入口](current-connections/46-source-mobile.png)。为实际隔离 Electron 构建，非安装包。首用和 Mobile 的混排仍可复现，协作未配置与通用设置的对象提示仍相近。没有连接服务、实际配对或执行模型。见 [构建身份](../SOURCE_BASELINE.md)。

历史交付证据 H01–H07 由 [证据映射](observations.json) 指向 Porpita checkout 的 `docs/porpita/evidence/20261109/`。其中包含已运行的 Git/保存、原生审批、附件、服务重连和工作台条件记录，与本轮回放分开使用。现有安装版与当前源码树不同；各回放的身份见 run 和映射。

回放过程的超时和未达到状态保留在对应的 `run.json`，比如早期 Tasks 只看到壳体、首用弹层抢占、Git fixture 入口未能用 IPC 登记直接走到默认检出。它们未作为对应流程成功；后续回放补到的现象有单独文件。原生焦点、OS 文件选择器、实机多 Host、真实消息、远端服务和目标模型没有由这组截图验收。

复现（已安装候选 11 与本机 Porpita checkout、Node/Playwright）：从 SPEC 根目录执行 `node tools/observe-installed.cjs <证据输出目录>`。可选 `--workbench`、`--tools-extra`、`--episode`、`--completed-profile --settings-census`、`--git`、`--chat`、`--restart`、`--connection`、`--auxiliary --completed-profile`。若安装路径或源码位置不同，用脚本支持的 `PORPITA_SPEC_EXE` 和 `PORPITA_SPEC_SOURCE` 指向实际位置；源码构建入口由 `PORPITA_SPEC_ENTRY` 指定。Windows 隐藏 renderer 需要可运行 Electron 和 CDP 的环境；脚本先核对隔离档案和窗口隐藏。图组索引可用于定位，不替代细节原图或全条件验收。
