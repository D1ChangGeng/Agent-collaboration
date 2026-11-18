# 第 50 轮 · Git 分支复核的选择、取消与回执

保留的 Git 分支可能含有尚未合并的提交。批量复核沿用 Orca 的分支、仓库和 HEAD 列表，加上执行 Host，方便辨认相同名称的分支。

- 打开复核时零选，焦点落在「取消」。单项或全选需要明确操作，选择计数随操作更新。缺少已确认 HEAD 的条目保持可读，选择不可用。没有合格项时全选和提交均禁用。
- Space 中 Esc、取消或关闭复核后，焦点回到复核入口。确认后将焦点交给筛选框，在同一结果栏更新剩余分支。失败的分支继续保留在复核中，可查看原有错误反馈。再开复核时从零选开始。
- 采用现有安全对话框、窄短窗滚动与通知避让。使用共享 Dialog 的进出过渡和减少动态设置。分支请求沿用原 Host/Runtime 命令和 expected HEAD 检查。Git 报告成功的项才从 Space 清单移除。
- 实况发现 Space 缺少文档语言，已绑定当前生效的 UI 语言。分支行使用已设置的 Host 显示名；本机缺少自定义名称时采用当前语言的本机标签。

对应 M.02.09。复用 `PreservedBranchBatchReviewDialog.tsx` 与 `force-delete-preserved-branch.ts`。在真实 Windows 窗口验证默认焦点、全选和清空、Esc、重开和单项提交，直接核对两个原 Git ref。重复仓库/Host、缺失或变化的 HEAD、拒绝后的另一次审阅和系统辅助技术留作相应环境的复验。 [打开复核](evidence/iteration-48-50-space-zh/i50-space-branch-review-empty.jpg) · [单项选择](evidence/iteration-48-50-space-zh/i50-space-branch-review-selected.jpg) · [提交结果](evidence/iteration-48-50-space-zh/i50-space-branch-review-result.jpg)
