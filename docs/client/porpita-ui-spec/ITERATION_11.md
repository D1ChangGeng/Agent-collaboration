# 第十一轮 · 固定范围的 Explorer 在两种呈现间移动

用户从指定工作树打开 Explorer，进入目录并筛选文件。在同一窗口把工具移入一个 Workspace，另一项目的 Chat 也在工作时，仍可从原目录继续浏览。将工具移回独立页后，打开选中的实际文件，经原 Worktree 的编辑器继续。

## 设计与试验边界

历史 Dock 的 `FileExplorer` 从全局选择读取显示根、内容搜索、Reveal、编辑器和删除上下文。完整移植这些行为前，需要验证固定 Scope 的呈现合同。采用 Orca 已有的文件名输入、文件浏览列表、图标、失败状态和目录读取。IntelliJ 工具窗提供同一工具用显式位置菜单移动的成熟参照。 [第八轮](ITERATION_08.md) · [IntelliJ 工具窗排列](https://www.jetbrains.com/help/idea/manipulating-the-tool-windows.html)

- 实例记录包含固定本地工作树、绑定的根、当前目录、名称筛选、选中位置及宿主。标题并列显示固定项目与当前目录，完整路径可查看。列表读取由原 Explorer 目录 API 处理。每个 Workspace 试验一个嵌入面板。同一范围再次打开时恢复同一对象。
- 工具菜单选择目标 Workspace，独立 Tab 收起，位置绑定到既有实例。切换到另一个 Chat 只影响输入焦点。返回独立 Tab 后，仍使用原名称筛选与选中项。面板内部焦点与滚动的完整恢复需要跟随原树组件迁移。
- 文件打开交给原生编辑器的已有路由，向原 Worktree 激活。面板保持可经顶层入口继续。失败和找不到原目录时在工具内部呈现。预览支持本地单目录列表、上下级导航和文件打开。完整树、Contents、变更/重命名、监控、远端分页以及插件仍由各自已有工具负责。

主要源码为 `WorkspacePreviewExplorer.tsx`、`workspace-preview-model.ts`、`readFileExplorerDirectory` 与 `openQuickOpenFile`。关联 G.09、R.07 和 J04/J07/J08/J12。

## 验收

在隔离 Git 仓库建立含 Markdown 的实际子目录。观察独立→嵌入→独立的连续帧、同一实例 ID、同一目录与筛选，在另一个 Worktree 会话被聚焦时检查读写归属。以窄窗验证文件在原 Worktree 真实渲染。

归档涵盖独立选中、嵌入时焦点回筛选、选中另一项目的 Chat、移回标签及原文件的编辑器画面。 [嵌入画面](evidence/iteration-09-11-windows/i11-move-panel.png) · [迁移连续帧](evidence/iteration-09-11-windows/explorer-placement/timeline.json) · [回原文件](evidence/iteration-09-11-windows/i11-original-file.png)
