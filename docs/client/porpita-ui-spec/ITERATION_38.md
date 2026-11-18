# 第 38 轮 · 从资源管理器返回现有 Browser 标签

资源树已经在工作树下展示打开的 Browser 标签。同一个工作树可能保有多个标签和页面。用户找到这一行后应能直接继续该标签中的既有页面。

Browser 行沿用资源树的层级、地球图标、现有标题和空指标列。整行可单击，Tab 进入后可按 Enter 或 Space。标题过长时单行省略，可访问名称保留完整标题。悬停和键盘焦点使用现有强调色。按工作树身份、Host 和 Browser 标签身份复查归属，使用已有分组和 Browser 激活能力显示原页面。定位成功后关闭资源弹层。有预览时显示原工作台，再次打开预览可继续原来的对象。目标不可用时保留资源弹层和当前工作对象，并在资源面板内反馈。

源码对应 `resource-usage-session-rows.tsx`、`resource-manager-browser-navigation.ts`、`use-resource-usage-actions.ts` 和 `browser-workspace-tab-activation.ts`。矩阵 A.03.14 对应 I.01 和 J11/J13。这个动作使用已打开标签的 active page 与 Browser 会话，原生资源统计仍按采样来源呈现。

Windows 回放以 Studio Explorer 为起点，从资源表按 Space 切到实际本机 Browser，核对标签和页面 ID、标签数量以及返回后的 Explorer 实例。Browser 来自上一轮打开的真实环回页面。资源表通过明确的样本和渲染器可见性信号展示，前台原生资源采样另行验证。 [英语连续帧](evidence/iteration-36-38-port-targets/resources-to-existing-browser/timeline.json) · [简中连续帧](evidence/iteration-36-38-port-targets-zh/resources-to-existing-browser/timeline.json)
