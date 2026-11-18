# 第 30 轮 · 当前工作树的端口

工作台原端口入口按活动工作树找刷新目标，列表则来自所有 Host 的汇总。组合式 Workspace 的 Chat 选中项和传统工作台的活动工作树可以不同。本轮把读数、入口和回源绑定到同一个工作树。

VS Code 的 Ports 视图把端口与可访问地址放在一起。JetBrains 的后端窗口先在抬头确定后端，再查看端口。Porpita 沿用 Orca 的状态栏入口、弹层、端口行及 Host 徽章。比较过全部端口、跟随控件焦点和跟随当前工作对象三种方式，选择按所选 Chat 的工作树或独立 Explorer 明确固定的工作树读取。嵌入 Explorer 取得焦点时，用量和端口仍沿用所选 Chat 的归属。 [VS Code Ports](https://code.visualstudio.com/docs/remote/ssh#forwarding-a-port--creating-ssh-tunnel) · [JetBrains 后端端口](https://www.jetbrains.com/help/idea/work-inside-remote-project.html#backend-control-center)

弹层标出 Host、项目与工作树。打开和刷新调用现有端口发现机制，只显示能确认属于该工作树根的监听项。计数以本次读取为准。组合式预览提供查看入口。要操作已有端口，使用「转到工作树」进入原工作台，回到预览后仍可继续原 Chat。

验收使用两个同名工作树，每个工作树启动一个只绑定到环回接口的临时服务。分别验证独立 Explorer、混合 Workspace 与原工作树跳转。源码见 `workspace-preview-ports-scope.ts`、`WorkspacePreviewPortsStatus.tsx` 和 `ports-status-popover-rows.tsx`。对应 A.03.06、G.05、J07 与 J11。

首轮预览实测混合 Chat 在 Local 和 Studio 之间切换。最终构建从两边真实工作树打开固定 Explorer，核对两个监听只在各自范围出现，并从弹层返回 Studio 原工作树。 [混合 Chat 首轮](evidence/iteration-30-32-mixed-trial/ports-scope-handoff/timeline.json) · [最终端口画面](evidence/iteration-30-32-ports/i30-ports-scope.png) · [回源连续帧](evidence/iteration-30-32-ports/ports-to-native-worktree/timeline.json)
