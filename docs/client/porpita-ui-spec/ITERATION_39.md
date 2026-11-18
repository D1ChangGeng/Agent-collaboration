# 第 39 轮 · 从资源管理器继续原终端窗格

[第 38 轮](ITERATION_38.md)建立了资源行到原 Browser 的交接。Resources 的终端行和本机 PTY 原本也能激活 Terminal，但在 Workspace 预览里，操作者仍可能看不到切换后的终端。同一标签有多个窗格时，需要恢复所选 PTY 的输入位置。

| 场景 | 行为 |
| --- | --- |
| Resources 和本机 PTY | 复用原来的资源行、箭头按钮与 Enter／Space。已绑定的分屏在标签名后显示按当前布局顺序计算的窗格编号。键盘事件由获得焦点的控件处理，行尾的结束按钮仍可独立操作。 |
| 从预览定位 | 复查工作树、终端标签、活跃 PTY 和唯一的稳定窗格 ID。定位成功后显示原工作台。资源弹层完成退出才将键盘焦点交给该窗格，避免关闭弹层时把焦点带回状态栏。另一窗格的独占展示可按既有逻辑收回。 |
| 目标已变化或身份不明 | 在资源弹层反馈，保留预览。配对 Host 采样行用于查看。 |
| 普通工作台 | 复用打开终端后仍可浏览资源的操作习惯。 |

首轮回放中两个可操作的分屏行都显示 `Terminal 1`。在两张资源列表中使用同一分屏树给它们标出顺序，输入焦点仍按稳定窗格身份交接。VS Code 的终端也提供现有标签、分屏和分屏焦点导航。 [VS Code Terminal Basics](https://code.visualstudio.com/docs/terminal/basics)

源码映射 A.03.15。涉及 `resource-session-navigation.ts`、`resource-session-bindings.ts`、`resource-session-labels.ts` 和 `use-resource-usage-actions.ts`。回放分别经 Resources 和本机 PTY 定位真实分屏，核对两个 PTY 身份、键盘焦点和原 Explorer。 [连续回放](evidence/iteration-39-41-resource-continuity/resource-to-original-terminal/timeline.json)
