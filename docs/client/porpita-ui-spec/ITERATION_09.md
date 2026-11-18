# 第九轮 · 在同一工作空间继续两个会话

同一项工作需要在两个项目的会话间往返。用户从已打开的本机会话选取两个对象，在一处并排阅读和编辑各自草稿。选择、改变宽度和关闭布局都以可再次继续为目标。此轮继承 D-001、D-002、D-006、D-007 及已通过的第七轮分隔线规则。

## 设计与试验边界

当前 Worktree 的 group tree 同时承载内容选择、布局保存和 PTY、Browser 等原生表面的可见状态。观察到的标题栏标签与布局随 Worktree 切换。将该树的 ID 改成用户 Workspace 会改变内容归属。拟用单独的布局记录保存现有会话引用，并在工作台预览中用原 Native Chat 组件呈现。VS Code Agents 的多 Chat 布局提供并排工作与恢复参照，现有 Orca 的原生分隔线、标签状态、会话和焦点机制承载本地结果。 [VS Code Agents 布局](https://code.visualstudio.com/docs/agents/run/agents-window-configuration#arrange-chat-tabs-and-groups) · [第七轮](ITERATION_07.md)

| 场景 | 预览内的选择 |
| --- | --- |
| 从已打开的会话建立布局 | 复用命令面板搜索与列表。标题和项目同列。同一会话再次选中时打开已有布局里的位置 |
| 两会话同时出现 | 保留各自 Tab ID、Worktree、原生会话 ID 和原本地运行目标。仅布局层维护活动 Pane 及比例 |
| 窄窗 | 每个 Chat Pane 保留 320 CSS px，分隔线另占 6px。可用宽度低于 646px 时显示当前 Pane，通过菜单浏览另一个。宽度变化临时限制呈现比例，放宽后恢复先前比例 |
| 关闭 / 再开 | 关闭顶层布局入口。打开列表保留该对象，恢复内容引用、当前 Pane 和比例。草稿由原 Native Chat 保存 |
| 引用不可用 | 在原位置给出不可用状态。恢复成功依赖正确 Host 与原会话记录 |

开发构建通过 `VITE_PORPITA_WORKSPACE_PREVIEW=true` 打开「工作空间（预览）」。布局记录放在隔离 renderer 的独立版本键。试验允许最多两个已有的本地结构化 Chat，视图读写沿用其真实对象。复用工作台标题栏、`NativeChatView.tsx`、`ResizeHandle` 和 `CommandDialog`。预览期间原工作台的 Chat 视图仍可保留于内存，其可见呈现与输入目标切走。正式集成需由同一个视图宿主移交生命周期。终端、浏览器、执行审批及更深 Pane 树需要各自的集成证据。

## 验收

以真实本机 Git 工作树中的两个 Codex Chat、两个不同草稿回放。观察并排、600px 单 Pane 与恢复、分隔线由 50% 键盘调至 55%、关闭并以同 ID 重新进入。在配置过的受控 Harness 上另验发送、等待审批与断线恢复。关联 D.03、D.07、R.04、T.04 与 J03/J04/J06/J13。

在 692×520 CSS px 记录两个 Pane 的可用宽度和已存比例。关闭后找回两个原会话草稿，可继续从独立布局使用。回放使用未登录 Codex，保留真实未登录提示。 [双会话](evidence/iteration-09-11-windows/i9-two-worktrees.png) · [缩窄与恢复](evidence/iteration-09-11-windows/workspace-pane-return/timeline.json) · [宽度测量](evidence/iteration-09-11-windows/pane-budget.json)
