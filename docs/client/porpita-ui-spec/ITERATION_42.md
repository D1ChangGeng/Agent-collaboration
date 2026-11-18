# 第 42 轮 · 本机 PTY 的批量选择范围

第 40 轮的简中实况里，单行操作已有「结束」，批量区仍显示 “Select all” 和 “End selected”。全选的实际范围由终端的可结束条件决定。 [原窄窗画面](evidence/iteration-39-41-resource-continuity-zh/i40-pty-availability.png)

| 状态 | 呈现和操作 |
| --- | --- |
| 未选 | 全选框未勾选，结束按钮显示 0。 |
| 已选部分可结束的终端 | 全选框呈混合态，结束按钮显示已选数量。可以继续逐行选择或在全选框按 Space。 |
| 已选全部符合条件的终端 | 全选框已勾选。在同一控件按 Space 可清除选择。 |
| 诊断失败、结束进行中或缺少结束权限 | 由现有诊断和会话状态决定可选范围，结束按钮只计算当前可执行的选择。 |

全选使用同一条可见标签与可访问名称。简中使用「全选可结束的终端」和「结束所选终端」。保留资源面板现有三态复选框与计数按钮，复用全选状态随行选择更新的成熟模式。 [PatternFly 批量选择](https://v4-archive.patternfly.org/v4/design-guidelines/usage-and-behavior/bulk-selection/)

对应 A.03.17。布局、选择和终止边界位于 `ResourcePtyPanel.tsx`、`use-list-multi-selection.ts` 和 `use-resource-pty-actions.ts`。回放在两个真实分屏的 PTY 上操作键盘选择并清空。结束条件和回执由现有聚焦测试补充。 [简中回放](evidence/iteration-42-44-resource-selection-zh/pty-eligible-selection/timeline.json)
