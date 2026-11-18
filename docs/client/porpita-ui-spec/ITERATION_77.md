# 第 77 轮 · Linux 键盘与读屏完成分支复核

接管后沿用工作台的保留分支通知和复核对话框。原行核对当前 Git 检出。Tab 到检出动作和复选框，空格选中，Enter 提交。用户从当前 Host 和路径判断可以继续的操作。

重点核验断线时的上次路径、勾选、焦点和暂停提交，恢复后取得同一 Runtime 的新读数。Git 再次遇到实际占用时，失败回执回到零选复核。解除占用后重新勾选并显式提交，检查 Linux 目标引用、Windows 同名引用和最终通知。

系统读屏需要听到影响当前决策的连接状态、检出结果与最终回执。实际 Orca 语音输出与 X11 焦点分开记录。静态可读性、真实播报、Git 状态和通知内容分别核对。 [第 74 轮](ITERATION_74.md) · [原生回放工具](tools/observe-linux-native.cjs)

从终端返回工作台后，用现有 Alt+T 将焦点移到通知，再用 Tab 到达复核动作。复核中的检出和恢复专用按钮留在所在分支行，异步回答由状态区域读出。

试跑中，工作树移除后终端接管焦点，Alt+T 之后仍停在 Terminal input。通知沿用 Sonner 列表，应用的键盘路由在终端捕获输入前处理既有快捷键。模态窗口中仍按原有可交互层级处理。 [试跑焦点记录](evidence/iteration-75-77-linux-trial/terminal-notification-focus.json)

最终回放在原行读到断线后的重连动作和恢复后的未检出结果。再次占用时读到拒绝和零选复核。完成删除后，可用 Alt+T、Tab 和 Orca 当前位置查询读出本次成功回执。第一次成功时自动播报未出现在记录中，后续以显式读取确认结果。 [断线录音](evidence/iteration-75-77-linux-en/i77-outage-voice.wav) · [系统读屏回执](evidence/iteration-75-77-linux-en/i77-explicit-retry-result.json) · [Windows 引用](evidence/iteration-75-77-linux-en/windows-peer-proof.json)

恢复后的未检出信息先出现在界面，Orca 的对应播报随后落在下一段记录开头。以两段相邻记录核对状态顺序。 [恢复画面与记录](evidence/iteration-75-77-linux-en/i77-original-row-recovered.json) · [排队后的播报](evidence/iteration-75-77-linux-en/i77-git-refusal.json)
