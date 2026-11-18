# 第 53 轮 · 保留已变化分支和再次提交

用户需要能结束已经失效的复核，也需要能处理可恢复的检出冲突。两个操作都从同一复核入口开始。

- 已变化分支可用「保留分支」移出此次 Space 复核。Git 中实读的分支引用继续存在。还有其他条目时停留在同一复核，焦点交给「取消」。最后一条移出时关闭 Dialog，焦点回 Space 筛选框。结果栏提示该分支的复核已结束。
- 对另一个工作树仍检出的分支，先在那个工作树切换分支，再回当前清单明确选择并提交。继续使用原 HEAD 比较删除，结果栏确认实际成功后撤去该条目。
- 复用现有 Button、焦点环与 Q.04 的 Dialog 入场。行移除跟随当前列表状态。按钮名称包含对应分支，可用键盘辨认和操作。 [WAI-ARIA Dialog 的焦点规则](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

对应 M.02.12。使用 `PreservedBranchBatchReviewDialog.tsx` 及 Space 的当前窗口回执。英语回放先保留变更分支，再解除另一工作树的检出并重试。简中回放先重试，再保留最后一条，共同验证两个焦点出口、Git 引用和结果栏。 [保留后的焦点](evidence/iteration-51-53-space-en/i53-space-branch-keep.jpg) · [最终回执](evidence/iteration-51-53-space-zh/i53-space-branch-recovered.jpg)
