# 第十四轮 · 拖放安排顶层分组

用户在一行顶栏将一个 Workspace 拖到组选择器，由菜单明确选择目的组。移组只改变顶层组织关系。Escape 回到原工作对象和焦点。

## 设计与采用

第十轮已在标题栏接通菜单移组与源组回退。Chrome 可把 Tab 拖进可见的组。Porpita 的窄窗常驻一个选择器，悬停明确投放目标，松手后从现有单选菜单选目的组。这延续了此前通过的夹具操作。采用 Orca `TabDragPointerSensor`、原 Radix 菜单及标题栏状态色。原右键动作与拖放提交共用同一对象移动逻辑。 [分组试验](GROUP_TRIAL.md) · [Chrome 标签组](https://support.google.com/chrome/answer/2391819?co=GENIE.Platform%3DDesktop&hl=en)

- 支持多个组时选择器作为投放目标。未到达目标、指针取消或放手后按 Escape 都保留原组与工作内容。
- 进入目标菜单时，用现有菜单标签指出要移动的对象，当前组不可选。确认后保持源组及其最近可用工作对象；查找后进入目标组的同一个 Workspace。
- 选择保留原 Pane、Native Chat 与 Explorer 实例。菜单和目标沿用原组件反馈及系统减少动态偏好。600px 条件优先验证操作与系统按钮的命中区域。

主要实现位于 `WorkspacePreviewTabs.tsx`、`WorkspacePreviewGroupPicker.tsx`、`workspace-preview-model.ts` 和原标签拖放传感器。关联 D.08、Q.03、T.04 及 J03/J06/J13。

## 验收

用真实 Pointer 路径完成两次投放，分别以 Escape 取消和明确目标提交。对照档案数据、可见焦点、组和对象 ID，并核对原有草稿与工具范围。右键菜单仍以第十轮路径复测。

拖动时菜单仅显示有效的分组去向，用户取消后可从原 Tab 继续键盘操作。 [取消过程](evidence/iteration-12-14-windows/group-move-cancel/timeline.json) · [提交及再打开](evidence/iteration-12-14-windows/i14-move-to-group.json)
