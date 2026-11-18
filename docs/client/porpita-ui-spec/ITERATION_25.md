# 第 25 轮 · 移动同一个 Explorer 并继续查找

用户在独立 Explorer 中找到文件，再将它放入正在工作的 Workspace。文件归属、目录、筛选和选择跟随实例，移回独立 Tab 时返回原查找位置。第 11 轮验证过显式位置菜单。IntelliJ 的工具窗口提供位置菜单和拖动两条路径。本轮采用已经存在的 Explorer 位置菜单，目标保持可见且键盘可操作。已有嵌入实例的 Workspace 暂不提供给另一个 Explorer。 [第 11 轮](ITERATION_11.md) · [IntelliJ 工具窗口的移动菜单](https://www.jetbrains.com/help/idea/manipulating-the-tool-windows.html#move-tool-windows)

独立 Tab 的标题为远端来源显示 Host 名称，面板标题沿用会话的 Host 徽章。选择「移至…」后独立 Tab 收起，打开目的 Workspace，焦点回到原筛选框。选择「作为标签打开」返回原组中的独立 Tab。列表随面板高度扩展，保持自己滚动。相同目录和筛选的滚动位置在本次预览内随实例保存，重启时由已选文件恢复可见锚点。加载、空目录和无匹配继续使用原浏览列表，减少动态时加载指示保持静止。

宽窗可并排看两个 Chat 与嵌入 Explorer。第一次回放在 280px 的嵌入面板里把项目和目录同时截短。嵌入后优先显示当前目录，完整路径可在标题处查看。600×460 目标为活动 Chat 保持至少 320 CSS px，沿用「切换窗格」处理双 Chat 的聚焦呈现。切换聊天焦点只改变输入去向，Explorer 保留自身 Host 与查找状态。另一个范围的独立 Explorer 仍可打开并保持自己的筛选。

主要源码是 `WorkspacePreview.tsx`、`WorkspacePreviewExplorer.tsx`、`RemoteFileBrowserEntryList.tsx` 与 `FileExplorerNameFilter.tsx`。对应 G.09.01、G.09.03、R.07 和 J07。

实际回放用 76 个条目验证了滚动。移入和移回之后，同一实例保留 `review-055.md`、原筛选及列表位置，焦点回到筛选框。600×460 时可在 360 CSS px 的 Chat 区继续工作，两边的可见来源仍不同。独立的本机 Explorer 返回后仍保持它自己的筛选与选择。 [移动连续帧](evidence/iteration-24-26-loopback-zh/explorer-placement-and-scroll/timeline.json) · [简中窄窗](evidence/iteration-24-26-loopback-zh/i25-narrow-workspace.png)
