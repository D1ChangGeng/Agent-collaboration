# 第 78 轮 · Wayland 原生键盘与系统读屏

第 75–77 轮获用户确认。本轮在同一台物理 Ubuntu 验收机使用隔离的 Wayland 合成器，复核原有配对、独立 SSH 接管和分支处理。沿用同一套设置、Worktrees、通知列表与 Git 复核界面。

Sway 接收键盘输入，由 Porpita 的 `xdg_shell` 窗口和 AT-SPI 提供界面及焦点。Tab 与 Escape 能退出添加服务器并返回原按钮，方向键可以定位旧工作树，接管后动作焦点保留在同一 SSH 卡片。使用标准 US evdev 键码的 Alt+T 可进入通知区。

在独立 SSH 接管后，用 Git 读取已移动的路径。断线时原复核行的焦点与选择保留，Orca 读出重连动作。Git 在暂时解除占用后重新发现分支被检出时仍拒绝删除，用户重新核对后显式提交。Linux 目标引用删除，Windows 同名引用保持。 [原生回放](evidence/iteration-78-80-wayland-en/run.json) · [断线录音](evidence/iteration-78-80-wayland-en/i78-outage-voice.wav) · [Windows 引用](evidence/iteration-78-80-wayland-en/windows-peer-proof.json)

本轮实测使用软件渲染的隔离 Sway 1.9、GNOME Orca 51.1 和英语浅色 1060×790。GNOME Shell 等其他 Wayland 合成器及组合键冲突继续按各自环境验收。 [来源与运行条件](SOURCE_BASELINE.md#第-7880-轮来源) · [原生会话](tools/linux-native-session.sh) · [回放工具](tools/observe-linux-native.cjs)
