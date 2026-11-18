# 第 55 轮 · 从 Space 打开已登记工作树

用户可从复核行直接进入正在占用分支的工作树。路径仍然显示，以便确认打开的对象。

Space 使用报告所对应的仓库、路径及执行 Host 查找唯一已登记实例，开放「打开工作树」。外部 checkout 以路径引导。主窗口再次核对工作树身份和实例后，沿用现有工作台激活。Space 待主窗口答复后显示打开结果。目标失效、窗口不可用或答复超时，原复核提供短提示与路径。

对应 M.02.14。按钮、焦点和窗口行为复用 Porpita 的原生模式。通过 Electron 的专用回复通道确认主窗口已完成应用内激活，然后按原窗口策略交接。 [Electron MessagePorts](https://www.electronjs.org/docs/latest/tutorial/message-ports)

Windows 实测从可见按钮进入正确的本机登记工作树，Space 保留原复核和选项。对同 ID 的过期实例执行协议检查，验证动作被拒绝。原生前台与双 Host 继续分别验收。 [Space 回执](evidence/iteration-54-56-space-zh/i55-space-checkout-opened.jpg) · [主工作台](evidence/iteration-54-56-space-en/i55-branch-open-checkout.png)
