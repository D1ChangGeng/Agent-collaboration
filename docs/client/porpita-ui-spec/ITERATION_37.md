# 第 37 轮 · 在原端口范围内恢复失效监听

第 34 轮在打开 Browser 前重新确认监听。失效后，用户原先需要关掉详情、重新打开之前的端口弹层，再找替换后的监听。新路径由详情中的刷新动作负责交接。

| 状态 | 操作与反馈 |
| --- | --- |
| 可打开 | 「在应用内浏览器打开」先按当前本机工作树重扫。保留按钮和键盘焦点，读取期间显示忙态。 |
| 原监听或 URL 已变 | 详情就地提示原因，同一个按钮变为「刷新端口」。扫描不可用或打开失败时保留原详情和打开动作，可重试。 |
| 用户确认刷新 | 关闭旧详情，打开同一工作树和 Host 的端口列表，并把键盘焦点交给列表弹层。读取、空、失败和结果使用已有端口列表状态。用户可选新行，也可按 Escape 返回状态栏。 |
| 成功打开所选行 | 再次确认这条监听，转到原工作树并打开 Browser。返回预览后仍可继续先前的工作对象。来源切换会终止旧详情和旧请求的交接。 |

采用现有状态栏端口扫描与 Dialog → Popover 的焦点交接，保留主题及动效。列表复用 Popover 的减少动态模式，读取图标在减少动态时静止。连续帧记录操作顺序，动画时长沿用组件实现。源码对应 `WorkspacePreviewPortDetails.tsx`、`WorkspacePreviewPortsStatus.tsx` 和 `workspace-preview-ports-scope.ts`，矩阵 A.03.13。

回放在详情打开时更换实际本机进程，核对旧行已失效。用 Enter 刷新原范围，核对焦点与 Browser 数量，再从列表选择替换后的端口并检查 Electron guest 已加载真实 HTML。 [英语连续帧](evidence/iteration-36-38-port-targets/refresh-stale-listener/timeline.json) · [简中连续帧](evidence/iteration-36-38-port-targets-zh/refresh-stale-listener/timeline.json)
