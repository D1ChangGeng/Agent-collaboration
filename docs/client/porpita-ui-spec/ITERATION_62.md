# 第 62 轮 · 以 Git 当前检出继续复核

用户查看当前检出并明确提交后，以该次 Git 回执更新复核。工作树已移动且分支仍被检出时，Git 拒绝删除，复核显示新的检出路径。返回的新复核从零选开始。释放实际占用后，用户重新勾选并提交；结果栏保留其余分支供后续复核。 [Git worktree 说明](https://git-scm.com/docs/git-worktree)

沿用原有分支比较、当前 Git 检出检查、结果栏和显式勾选。真实 Git 校验发生在每次提交时，界面的上次路径只帮助排查。

对应 M.02.21。回放移动实际 worktree 后触发拒绝，核对新路径与原 Git 引用。再次复核前切换移动后工作树的分支，然后提交当前选项，核对仅该项被成功删除。 [新路径实况](evidence/iteration-60-62-space-zh/i62-space-checkout-refreshed.jpg) · [完成本项](evidence/iteration-60-62-space-zh/i62-space-checkout-resolved.jpg)
