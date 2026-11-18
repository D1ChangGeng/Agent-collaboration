# 第 34 轮 · 从本机端口打开原工作树的 Browser

本机工作树的端口详情提供「在应用内浏览器打开」。按钮确认本次读取仍有同一监听及地址，再调用原工作树的 Browser。详情关闭或来源切换时，待处理结果退出。原监听退出后，当前视图会请用户刷新再试。成功后 Browser 在原工作树打开，Workspace 预览可从原入口继续。配对 Host 的详情提供端口归属，操作入口经上一轮的「转到工作树」。

采用既有端口发现、地址解析、工作树激活与 Browser 标签。按钮复用原详情窗口的底部操作区，读取时保留原标签。选择本机工作树作为本轮 Browser 打开的范围。测试用实际环回页面及替换后的监听验证跳转与失效反馈。

源码见 `WorkspacePreviewPortDetails.tsx`、`workspace-port-actions.ts` 与 `workspace-port-urls.ts`。对应 A.03.10、G.05 和 J11–J13。

两组回放都观察到旧监听退出时的刷新提示与应用内 Browser 加载后的真实页面标题。 [替换及打开过程](evidence/iteration-33-35-port-resources/port-to-browser/timeline.json) · [应用内 Browser](evidence/iteration-33-35-port-resources-zh/i34-port-browser.png)
