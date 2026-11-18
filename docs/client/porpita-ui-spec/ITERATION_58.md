# 第 58 轮 · 返回时恢复原复核焦点

从主工作台使用返回入口，回到已经打开的同一个 Space 窗口。原 Dialog、当前勾选及列表内容均沿用当前状态。主窗口活动工作树保持原位。

- Space 收到这次复核的返回请求后，焦点回最近成功打开工作树的按钮。若该控件已离开可操作范围，用同一 Dialog 的「取消」作为回焦点。焦点可以滚动到目标可见位置，焦点样式继承原 Button。
- 使用 Space renderer 的焦点应答确认当前复核仍可恢复。主进程随后按现有原生窗口策略定位窗口。该动作不要求重新提交分支。
- 复用前一轮的专用 MessagePort 回复模式及共享 Dialog 控件。 [Electron MessagePorts](https://www.electronjs.org/docs/latest/tutorial/message-ports) · [WAI-ARIA Dialog 焦点说明](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

对应 M.02.17。隐藏 Windows 客户端以键盘从真实主工作台返回，核对 Space 窗口标识、已选分支和控件焦点。原生前台切换与读屏按真实设备单列验收。 [返回后的复核](evidence/iteration-57-59-space-zh/i58-space-review-returned.jpg)
