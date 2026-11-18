# 第 54 轮 · 识别占用分支的工作树

第 53 轮的复核可显示「已在别处检出」并提示切换分支。用户需要知道应到哪个工作树操作，尤其是同仓库存在多份 checkout 时。 [原复核画面](evidence/iteration-51-53-space-zh/i52-space-branch-refusals.jpg)

在原拒绝行补充「检出路径」。路径来自拒绝当次的 `git worktree list --porcelain`，只在 Git 报告单一且可辨认的检出时展示。对外部 checkout 也保留路径，方便在环境中定位。多个候选、临时 Git 保留或旧 Runtime 未给出路径时继续显示通用拒绝。首版中按钮占用了路径的横向空间，最终让路径独占一行并使用原列表滚动。 [路径首版](evidence/iteration-54-56-space-trial/i54-checkout-path-trial.jpg)

对应 M.02.13。复用 Git 原删除校验及复核行，以一次性仓库的登记 checkout 和带空格、中文目录名的外部 checkout 核对两个实际路径和分支引用。 [登记路径](evidence/iteration-54-56-space-zh/i54-space-checkout-paths.jpg) · [外部路径](evidence/iteration-54-56-space-zh/i54-space-checkout-external.jpg)
