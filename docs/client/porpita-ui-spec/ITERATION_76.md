# 第 76 轮 · Linux 键盘进入独立 SSH 接管

从 Linux 工作树列表定位原独立 SSH 工作区。键盘进入原工作区的确认状态，打开对应 SSH 设置并连接同一目标。继续复用既有工作树列表、工作区确认与 SSH 卡片。

工作区操作绑定实例与 Host。读取目标主机和接管反馈时保持当前操作对象明确。SSH 连接完成后比对托管 Runtime、原项目 ID 和仓库路径。键盘和系统读屏沿同一路径核验原确认、连接与后续返回。

验收用 Linux 实机上的独立 OpenSSH 监听、实际 Git 项目、一次性密钥和隔离的 Porpita 资料。Windows 配对通道同时保持可查询。 [第 73 轮](ITERATION_73.md) · [原生回放工具](tools/observe-linux-native.cjs)

初次实机回放中，Delete Workspace 走悬停目标，方向键定位后无法进入同一确认。修订让拥有焦点的 Worktrees 列表使用其当前条目，校验列表归属及 Host 身份。SSH 卡片在连接过程中保持主按钮节点，连接状态在原行提供系统播报。 [试跑记录](evidence/iteration-75-77-linux-trial/keyboard-trial-run.json) · [W3C 屏幕阅读器状态消息](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

从设置回到工作台时，终端会接收 Tab。使用已有的 Ctrl+Shift+0 将焦点交给 Worktrees 列表，再用方向键和删除快捷键操作当前工作区。

真实回放确认原项目 ID 与路径保持，动作焦点留在连接按钮所在位置。Orca 已读出连接中和 Connected。首次使用的 Chat UI 卡片可能遮住主机行右侧，键盘焦点和播报按实际控件校验。该视觉覆盖继续登记在 O.01。 [接管截图](evidence/iteration-75-77-linux-en/i76-adopted-ssh-host.png) · [焦点和播报](evidence/iteration-75-77-linux-en/i76-adopted-ssh-host.json)
