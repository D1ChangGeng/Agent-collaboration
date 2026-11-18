# 第 51 轮 · Space 分支清理的批次结果

旧版在真实混合结果中移除一个分支，保留两个。工具栏仍只有工作树数量与保留分支入口，分支清理的数字和两段技术错误一起出现在通知里。关闭通知后可重开清单，工作对象的结果缺少同一位置的说明。 [第 50 轮基线](evidence/iteration-51-53-space-baseline/i51-old-branch-refusal-toast.jpg)

保留第 50 轮提交后回到筛选的流程。原结果栏在工作树结果下显示分支清理进度和结果，确认数来自该次实际成功的 Git 操作，退回数来自同一批未获确认的条目。右侧保持待复核数量及入口。筛选变化时继续显示原结果。空间不足时采用同一结果栏的换行布局。

留在复核窗口等待会占住 Space。继续沿用通知会使结果在关闭后难以回查。结果进入原工具栏后，用户可继续筛选并按需重开。等待期间入口禁用，不能确认结果时使用专门提示。这些文字随结果直接变化，沿用共享 Button 和状态栏样式。

对应 M.02.10。复用 `workspace-space-manager-toolbar.tsx`、`use-workspace-space-kept-branches.ts` 和 `preserved-branch-batch-toast.tsx`。Windows 隔离仓库以三个实际分支验证成功和两次拒绝的数量、Git 引用、筛选及回焦。 [英语结果](evidence/iteration-51-53-space-en/i51-space-branch-batch-result.jpg) · [简中窄窗](evidence/iteration-51-53-space-zh/i51-space-branch-batch-result.jpg)
