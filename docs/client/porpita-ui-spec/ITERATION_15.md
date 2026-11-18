# 第十五轮 · 从侧栏继续已打开的会话

「会话」是工作台左侧栏的一个视图，与项目列表和活动视图共用侧栏。进入后可持续查看本机已打开的 Native Chat。全局查找仍用于快速跳到已打开的会话、工作树和其他工作对象。Vault 提供历史查询。

## 设计与复用

对照现有 Activity 的常驻列表和第十三轮的模态搜索。常驻方式适合边看项目和打开位置边切换会话，模态搜索适合短时键盘导航。VS Code 的常驻 Agent Sessions 视图展示会话列表与工作区边界，IntelliJ 把快速全局搜索与可持续检查结果的工具窗口同时保留。本轮沿用 Orca 的侧栏、`Command` 内联变体、已开 Tab 标题、Harness 图标与搜索激活路径。 [Orca Activity 实际界面](evidence/current-source/35-activity.png) · [第十三轮实际搜索](evidence/iteration-12-14-windows/i13-location.png) · [VS Code 会话管理](https://code.visualstudio.com/docs/agents/run/sessions/manage-sessions#find-and-resume-a-session) · [IntelliJ 搜索](https://www.jetbrains.com/help/idea/searching-everywhere.html)

| 触发 | 呈现与行为 |
| --- | --- |
| 从工作台打开「会话」 | 展示有效的本机结构化 Chat Tab。名称沿用原 Chat 标题，次行显示项目、工作树和 Harness，已在打开的 Workspace 中则另显示打开位置。超长内容截断，完整文字随选项提供。 |
| 输入名称或归属 | 查询按会话标题、来源、Harness 和 Workspace 名称匹配。键盘从输入使用上下键浏览并按 Enter 打开，鼠标直接点行。行高亮标记当前 Enter 候选。没有打开的本地 Chat、当前筛选无匹配分别有状态提示。 |
| 选择已在 Workspace 的会话 | 按工作树、Tab、原生会话和所属组重新校验，优先激活打开的 Workspace 和对应 Pane。继续向目标 Composer 交接焦点，保留原会话与草稿。 |
| 选择其他本机已开会话 | 经原 Worktree 路由激活该 Chat 和 Composer。身份不再有效时沿用原位不可用提示，准入阻止的操作沿用工作台反馈。 |
| 返回工作树 | 左栏恢复进 Workspace 前的视图与该次应用运行的会话查询。项目显式定位仍会返回项目列表。 |

源码入口为 `SidebarHeader.tsx`、`SidebarSessionIndex.tsx`、`session-index-model.ts` 和 `workspace-preview-navigation.ts`。以实际 Tab 记录和本地工作树 owner 为来源，拒绝不能解析的来源及有歧义的 Tab。开发预览使用现有开关，配对 Web 窗口按现有边界处理。此切片的行对应已开 Tab。跨 Host、未打开的原生会话与交互状态归属继续走完整 Session Index 目标。

## 验收

在两个真实本地 Git 项目建立三条同 Harness 的 Native Chat，其中两条组成同一 Workspace。逐项核对列表来源、目的地、鼠标打开原 Worktree 以及键盘命中 Workspace，断言选择前后的 Tab 与会话引用、两条草稿和目标焦点。 [窗口截图](evidence/iteration-15-17-windows/i15-directory.png) · [键盘交接](evidence/iteration-15-17-windows/directory-to-workspace/timeline.json) · [断言](evidence/iteration-15-17-windows/session-index-checks.json)
