# Orca工作台呈现层源码定位

固定上游：`stablyai/orca@9055eb9344dac1300311337cb1f0040d8094e3c2`，MIT许可见相邻采用研究的原始LICENSE。

这里保存4份完整原文件及Sidebar主体的1–150行摘录，供采用研究定位。它们是源码证据，不是完整可构建checkout。

- `Sidebar.tsx`实际转到`sidebar/index.tsx`。摘录中可见既有workspaces／agents主体选择、`agentsGroupBy`、折叠和滚动位置维护。若后续增加组织分组，应先研究这些既有入口与store。
- `TerminalWorkbenchContainer.tsx`处理隐藏工作台与浏览器guest持续合成、键盘／辅助技术隔离。
- `TerminalSplitWorkspaceSurfaces.tsx`保留各工作空间的layout、可见性、后台挂载与cold parking。
- `TerminalTitlebarTabs.tsx`复用TabBar与workspace store，连接已有文件／浏览器／模拟器／终端操作。

这些关联说明为何采用应保留完整源实现。单独复制静态布局不能带走后台、恢复与上下文连续性。本轮未安装、编译或运行这套应用。

完整文件的原始Git blob与URL见`source-manifest.json`。摘录来源为同commit的`src/renderer/src/components/sidebar/index.tsx`，Git blob `29bfecfa9f5c21e346ce3e1ebd8e67369c861177`，范围1–150行。
