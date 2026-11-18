# 第 44 轮 · Space 清理审阅的可见范围

筛选会保留已有选择。当前删除流程通过表格可见行计算目标，但原选中栏只统计可见行，筛选隐藏所有选中项时也会消失。操作者需要知道保留了哪些选择，以及打开清单会纳入几个工作树。

| 场景 | 呈现和操作 |
| --- | --- |
| 两个可审阅的工作树均可见 | 显示当前列表的项目数与估计可回收空间。按钮显示「查看删除清单（2）」。 |
| 筛选仅显示一个 | 显示一项在当前列表及一项在筛选范围外。审阅按钮和估计空间按当前可见且满足资格的项目计算。 |
| 所有已选项均被筛选隐藏 | 保留计数和清除选择入口，审阅按钮显示零项。 |
| 移除筛选或取消审阅 | 既有选择仍可查看。使用「清除选择」可清除可见项与筛选隐藏项。 |

复用 Space 表格、选中栏、保护状态和现有删除 Dialog。筛选保留熟悉的选择方式，范围提示与审阅目标使用当前表格可见性。审阅由既有工作树身份、保护和确认流程决定。 [PatternFly 工具栏](https://v4-archive.patternfly.org/v4/design-guidelines/usage-and-behavior/toolbar/)

对应 M.02.03。模型投影位于 `use-workspace-space-manager-projection.ts`，入口在 `workspace-space-manager-toolbar.tsx`。回放扫描两个临时链接工作树，核对受保护的主工作树、仅审阅一个可见目标、取消以及清空筛选。 [筛选后的选中栏](evidence/iteration-42-44-resource-selection-zh/i44-space-filtered.jpg) · [单项审阅](evidence/iteration-42-44-resource-selection-zh/i44-space-one-target-review.jpg)
