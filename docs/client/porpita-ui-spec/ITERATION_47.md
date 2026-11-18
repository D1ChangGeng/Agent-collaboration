# 第 47 轮 · 部分清理结果与剩余工作树重试

多项清理在执行时可能得到不同结果。可见反馈按同一批确认目标与已完成子集计算，行内保留原有失败原因。

1. 审阅后确认两个实际工作树。批次处理中显示总数。
2. 一项成功时，Space 显示「已删除 2 个工作区中的 1 个」。成功项退出列表，保留项在对应行持续显示失败原因，主窗口同步后仍可查看。
3. 原因排除后刷新 Space，从当前可见合格项再次打开审阅。重试成功后显示该次确认的结果。

复用已批准的筛选和审阅范围、完成回写、行内错误和原有非强制删除路径。首次实况中，主窗口同步后行内原因消失，提示条仍报告失败。Space 在合并主窗口状态时保留本窗口更新的清理项。 [首轮实况](evidence/iteration-45-47-space-cleanup/i47-space-overwritten-trial.jpg)

对应 M.02.06。路径经过 `worktree-delete-execution.ts`、`workspace-space-worktree-row.tsx` 和 `space-window-state.ts`。回放在临时工作树的批量审阅打开后写入一份测试文件，使普通删除出现真实的部分结果。重新接收主窗口状态后检查失败标记与原因，再移除该测试文件并重新审阅剩余工作树。 [部分结果](evidence/iteration-45-47-space-cleanup-zh/i47-space-partial.jpg) · [重试后](evidence/iteration-45-47-space-cleanup-zh/i47-space-retried.jpg)
