# 第 52 轮 · 分支变化与检出占用

旧版关闭错误通知后，实际已变化的分支和正在另一个工作树检出的分支均回到可选行。两行沿用「可能含未合并的提交」。查看用户刚刚遇到的拒绝需要回忆通知。 [旧版重开复核](evidence/iteration-51-53-space-baseline/i52-old-branch-refusal-review.jpg)

- 列表保留分支、仓库和 Host。Git 拒绝删除后，只有从实际分支引用读到不同提交才能标记「分支已变化」。行内显示原提交和读到的新提交，旧记录的复选框禁用，也不计入全选。首版截图里，禁用样式使旧提交文字变淡，最终版沿用正文与次级文字层级。
- 已在另一个工作树检出时显示检出状态和后续动作。Git 未能确认结果且没有读到新提交时，用「结果未确认」，原诊断仍可查看。
- 提交按原 Host、Runtime、worktree 和分支选择目标，实际删除仍比较原 HEAD。最近一次读数用于解释拒绝。新提交需要在仓库中复核。 [Git 引用更新与旧值校验](https://git-scm.com/docs/git-update-ref)

对应 M.02.11。沿用 `PreservedBranchBatchReviewDialog.tsx` 的安全 Dialog、行结构和复选框。Git 通过 `worktree-branch-removal.ts` 与 `preserved-branch-cleanup.ts` 回传可辨别的拒绝原因。Windows 回放在确认前实际推进分支并建立另一个检出，核对两个提交、二者不同的选择范围、全选与取消。底层聚焦测试验证同一分支 HEAD 上的锁冲突呈现为未确认。配对 Runtime 在真实跨 Host 情形下的错误传递继续单列验收。 [英语复核](evidence/iteration-51-53-space-en/i52-space-branch-refusals.jpg) · [简中复核](evidence/iteration-51-53-space-zh/i52-space-branch-refusals.jpg)
