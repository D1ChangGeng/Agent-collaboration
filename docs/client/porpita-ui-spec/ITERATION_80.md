# 第 80 轮 · 首次使用卡片避让设置与关键操作

终端为默认界面时，Chat UI 首次使用卡片继续沿用原来的右下角通知栈。进入设置或打开模态对话框时暂停展示。回到工作台后，当前会话中尚未处理的卡片可以接着出现。

设置中尚未展示的提示等待设置退出再开始展示。已展示的卡片按当前可见性切换，保留本次提示状态。模态对话框继续管理自身的焦点和退场。

在 Wayland 1060×790 基线中，卡片覆盖 SSH「连接」按钮中心。修订后按钮中心命中通过，Tab 到达时焦点可见，连接成功后焦点留在同一动作位置。卡片在返回工作台时恢复，在打开分支复核时避让。其他浮层叠加与更窄窗口按对应场景复验。 [基线画面](evidence/iteration-78-80-wayland-trial/i80-ssh-settings.png) · [修订画面](evidence/iteration-78-80-wayland-en/i80-ssh-settings.png) · [恢复画面](evidence/iteration-78-80-wayland-en/i80-card-returned.png)
