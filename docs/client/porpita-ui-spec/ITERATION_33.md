# 第 33 轮 · 工作树端口详情

第 30–32 轮的状态栏端口列表回答了“这个工作树有哪些监听”。这一轮继续确认一条监听的 Host、工作树、地址和进程。详情沿用 Orca 原 Ports 的对话框、字段和图标，补充与列表相同的 Host 徽章和工作树名。已有的 Ports 侧栏按 Host 能力显示。详情入口在已确认的工作树使用同一份受控结果。

比较了把详情放进列表行、跳到工作台侧栏、复用已有详情对话框。采用第三种，保留简短列表并给字段留出可读空间。通过端口行的详情按钮进入后，Esc 返回对应 Host 的状态栏入口。原工作对象变化时，详情随原列表退出。 [VS Code 的端口与地址操作](https://code.visualstudio.com/docs/debugtest/port-forwarding) · [JetBrains 后端面板](https://www.jetbrains.com/help/idea/work-inside-remote-project.html#backend-control-center)

源码见 `WorkspacePreviewPortsStatus.tsx`、`WorkspacePreviewPortDetails.tsx`、`local-port-details-dialog.tsx` 与 `ports-status-popover-rows.tsx`。对应 A.03.09、G.05 和 J13。

两种语言都用实际监听核对 Host 与地址，并验证键盘进入和关闭后焦点返回。详情的协议和证据值沿用原诊断字段。 [切换连续帧](evidence/iteration-33-35-port-resources/port-detail-origin/timeline.json) · [简中窄窗](evidence/iteration-33-35-port-resources-zh/i33-port-details.png)
