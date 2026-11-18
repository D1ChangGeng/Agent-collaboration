# 第 64 轮 · 核对结果留在原复核

用户处理占用后可在同一行再次核对。Git 未发现检出时显示「未检出」，最近得到的路径标成「上次检出路径」。核对按钮保持焦点，当前分支勾选保留。已确认 HEAD 变化的分支显示原有「分支已变化」状态，撤下该项勾选并沿用保留分支动作。未能确认时保留已知路径及再次核对入口。

复用原复核的分支状态、勾选、保留操作和行内消息。核对中显示进度，暂时禁用该行的核对和打开动作。读数只对发起它的复核有效。关闭或重新打开复核时以当前记录为准。路径和提示使用状态区域，结果在当前位置更新，沿用现有对话框动效。 [WAI 状态消息](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

英语首轮回放中，HEAD 变化后的行内操作使核对按钮部分落在列表边缘之外。结果更新时，仍有焦点的核对按钮会滚到可见位置。 [首轮画面](evidence/iteration-63-65-space-trial/i64-focus-before-scroll.jpg)

对应 M.02.23。双语回放切换移动后工作树的分支，核对未检出、原勾选及焦点。英语另推进另一条真实 Git 分支的 HEAD，验证只撤下变化项。简中暂时重命名分支，验证查不到引用时保留原行，恢复引用后可再次核对。 [简中未检出](evidence/iteration-63-65-space-zh/i64-space-checkout-available.jpg) · [英语 HEAD 变化](evidence/iteration-63-65-space-en/i64-space-checkout-head-changed.jpg) · [简中结果未确认](evidence/iteration-63-65-space-zh/i64-space-checkout-unconfirmed.jpg)
