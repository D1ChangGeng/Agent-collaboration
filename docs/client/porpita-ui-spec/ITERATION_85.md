# 第 85 轮 · SSH 目标选择与 Orca 键盘辨识

三个连接按钮的基线可访问名称都是「Connect」。实机 Tab 到任意一个连接按钮时，Orca 没有随焦点读出该条的完整别名与地址。 [基线按钮与播报](evidence/iteration-84-86-gnome-baseline/i84-baseline-beacon.json)

按照现有可见操作、别名、地址的顺序组合连接按钮的可访问名称。复选框保留选择动作和别名，并加入对应地址。Tab 与 Shift+Tab 继续沿既有控件顺序，Space 只改变复选框所在条目的批量选择。 [W3C 可访问名称中的可见标签](https://www.w3.org/WAI/WCAG22/Understanding/label-in-name.html)

实机 Tab 到三个「Connect」时，Orca 分别读出了完整别名、用户名、地址和端口。复选框也读出完整身份，Space 勾选 atlas 后三个监听的 TCP 与认证计数保持原值。向前和向后 Tab 均可在同一条目的复选框与连接按钮之间移动。 [三个焦点片段的录音](evidence/iteration-84-86-gnome-en/host-focus.wav) · [Beacon 读屏记录](evidence/iteration-84-86-gnome-en/i85-focus-beacon.json) · [勾选](evidence/iteration-84-86-gnome-en/i85-bulk-selection.json)
