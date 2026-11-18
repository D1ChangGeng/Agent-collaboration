# 第 63 轮 · 提交前核对当前 Git 检出

移动工作树后，Space 已能保留原复核和上次检出的路径。用户要在提交前知道该分支现在检出在哪里。第 62 轮的路径更新来自 Git 拒绝删除的回执。 [第 62 轮路径回执](evidence/iteration-60-62-space-zh/i62-space-checkout-refreshed.jpg)

本机 Space 的检出拒绝行提供「核对检出」。它按原保留分支的仓库、名称和 HEAD 读取 Git。工作树移动且仍检出该分支时，同一处路径更新到新的位置。新路径有唯一登记的当前工作树时，可沿用「打开工作树」动作。核对在当前复核行反馈，检出路径继续用原等宽样式呈现。 [Git 工作树列表](https://git-scm.com/docs/git-worktree) · [Git 引用读取](https://git-scm.com/docs/git-rev-parse)

对应 M.02.22。复用原分支清理记录、主机边界和 Git 工作树解析，原行使用 Outline Button。Windows 回放实际移动工作树后从状态栏返回，按 Enter 核对路径并比对两个分支的 Git 引用。 [简中实况](evidence/iteration-63-65-space-zh/i63-space-checkout-current.jpg)
