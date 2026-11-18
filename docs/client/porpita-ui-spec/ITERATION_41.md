# 第 41 轮 · 从资源摘要在 Space 查看磁盘结果

资源管理器已有紧凑的磁盘摘要。旧入口在开窗请求前就关闭了资源弹层，失败后需要用户重开摘要。新的交接让同一次扫描和当前预览贯穿成功与重试。

1. 使用现有「扫描」读取工作树磁盘用量，摘要保留大小和观察时间。
2. 使用「在空间管理中查看」。等待窗口请求时保留摘要与原按钮焦点，防止重复请求。
3. 请求成功后关闭资源弹层，进入既有独立 Space 窗口查看扫描结果。关闭窗口后继续原 Explorer。
4. 请求失败时在 Space 摘要内显示可重试反馈。错误可换行，原对象和结果可继续读取。

复用现有摘要、Space 页面、独立窗口和磁盘分析服务。状态栏中的内存读数和 Space 磁盘结果各自保留来源。

源码映射 M.02.01。涉及 `WorkspaceSpaceCompactPanel.tsx`、`ui-slice-view-actions.ts`、`WorkspaceSpacePage.tsx` 和 `workspace-space-window.ts`。回放检查实际扫描、模拟打开失败、实际独立窗口及原 Explorer。 [连续回放](evidence/iteration-39-41-resource-continuity/resources-to-space/timeline.json) · [独立窗口](evidence/iteration-39-41-resource-continuity/i41-space-window.jpg)
