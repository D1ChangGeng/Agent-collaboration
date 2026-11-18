# 第 81 轮 · GNOME Shell 系统快捷键与 Porpita 焦点交接

第 78–80 轮获用户确认。延续同一 Porpita 图形构建，从 Sway 进入物理验收机上的 GNOME Shell Wayland。复用原有配对、独立 SSH 接管、Worktrees 导航和通知键盘入口。

按 GNOME 的预设键验证 Super 打开概览、Super+V 打开系统通知列表、Super+Tab 切换应用。系统界面退出后，应回到配对表单原输入，随后应用内 Escape 应关闭表单并返回「添加服务器」。Alt+T 应交给 Porpita 通知列表，方向键仍可定位当前 Host 的工作树。 [GNOME 预设快捷键](https://help.gnome.org/gnome-help/keyboard-shortcuts-set.html) · [上轮 Sway 回放](ITERATION_78.md)

由 Mutter 接收标准 US 键码，使用 Mutter 的合成器画面核对系统界面，由实际客户端提供工作流状态与控件焦点。GNOME Shell、窗口状态与应用内焦点分别从对应记录核对。

实机按 Super 从配对表单打开概览，按 Super+V 打开系统通知，并用 Super+Tab 在 Porpita 与另一个 GTK 应用间切换。每次回到 Porpita 时，原「访问链接」输入保有焦点。随后应用内 Escape 返回「添加服务器」，再次进入表单完成 Windows 对端配对。 [活动概览](evidence/iteration-81-83-gnome-en/i81-activities.png) · [系统通知](evidence/iteration-81-83-gnome-en/i81-system-notifications.png) · [切回原表单](evidence/iteration-81-83-gnome-en/i81-switch-return.json)

配对后沿用现有的 Worktrees 快捷键和 Alt+T，完成独立 SSH 项目接管、分支复核和断线后原行重连。验收以 GNOME Shell 46.0、Mutter 46.2、US 键盘布局和原生 Wayland 窗口为范围。自定义系统按键、其他输入布局及 Orca 的桌面启停键各有自己的验收路径。 [完整回放](evidence/iteration-81-83-gnome-en/run.json) · [断线读屏](evidence/iteration-81-83-gnome-en/i81-outage-voice.wav)
