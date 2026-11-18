# 第 45 轮 · Space 审阅的取消与焦点返回

第 44 轮验证了删除清单的范围。本轮接续从 Space 多选栏进入清单后的键盘操作。原对话框打开时会主动聚焦删除按钮。

- 通过「查看删除清单」进入时，沿用现有目标预览、工作树路径和确认结构，初始焦点落在「取消」。
- 用 Enter 在「取消」处结束，或者用 Esc 关闭后，焦点回到打开审阅的按钮。当前筛选与选择可继续使用。
- 审阅入口在关窗时已经不可用，焦点交给 Space 的搜索框。

复用 Porpita 对话框、按钮和焦点回调。WAI-ARIA APG 将低破坏性动作列为难以撤销时的初始焦点，并说明关窗后回到调用控件或工作流的下一处。 [WAI-ARIA 对话框指南](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

对应 M.02.04。入口在 `workspace-space-manager-toolbar.tsx`，焦点接力通过 `delete-worktree-flow.ts` 和 `DeleteWorktreeDialog.tsx`。回放读取 Space 中实际确认范围，验证 Enter 取消及焦点返回。 [初始焦点](evidence/iteration-45-47-space-cleanup-zh/i45-space-review-cancel-focus.jpg) · [取消返回](evidence/iteration-45-47-space-cleanup-zh/i45-space-review-returned.jpg)
