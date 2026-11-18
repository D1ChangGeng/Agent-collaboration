# 第 43 轮 · Space 目录图的进入与返回

第 41 轮的简中 Space 将进入目录的 “Zoom” 显示成「飞涨」。目录图改变的是当前显示层级。工作区图块也会在进入时退出渲染，需要为键盘用户提供新的焦点位置。 [原 Space 画面](evidence/iteration-39-41-resource-continuity-zh/i41-space-window.jpg)

| 层级 | 呈现和操作 |
| --- | --- |
| 工作区概览 | 图表以「工作区大小」命名。图块的可访问名称含工作区和大小，可用 Enter 进入。标题栏的「查看目录」操作当前工作区。 |
| 目录视图 | 显示「目录大小」和当前工作区。进入后焦点落在「返回工作区概览」。 |
| 返回 | 由返回按钮恢复工作区图表，焦点回到「查看目录」。数据暂时无可用入口时，整个图表可接收程序化焦点。 |

沿用 Space 的树图、配色、图块比例和按钮样式。GNOME Disk Usage Analyzer 的方块也能成为图表的当前起点，Porpita 的层级按工作区与该工作区的顶层项表述。 [GNOME 树图行为](https://help.gnome.org/baobab/pref-view-chart.html)

对应 M.02.02。交互在 `workspace-space-treemap.tsx`，扫描结果和层级状态来自 Space 既有视图模型。回放由真实扫描中的主工作树打开目录图，检查两种进入方式与返回焦点。 [目录层](evidence/iteration-42-44-resource-selection-zh/i43-space-folders.jpg) · [返回概览](evidence/iteration-42-44-resource-selection-zh/i43-space-overview.jpg)
