# 第十三轮 · 从聊天搜索回到正在工作的 Workspace

用户在「已打开的聊天」找到一个正在同事协作、排查或核对文件的 Chat。结果行说明将在哪个 Workspace 打开。选择后聚焦该工作空间中同一个会话，保留另一侧内容和工具范围。 [第六轮](ITERATION_06.md) · [VS Code 会话查找与分组](https://code.visualstudio.com/docs/agents/run/sessions/organize-sessions)

## 设计与采用

可以继续总是回到单一 Worktree，也可以把所有历史结果融合进顶层工作空间搜索。这轮采用范围明确的入口交接，复用 Orca 的跳转面板、语言与列表状态。会话已有打开的预览 Workspace 时，附加一行目的地，原项目、Host 和 Harness 仍用于辨认来源。若只找到原工作树会话，则沿用当前跳转入口。这条路径建立 Session Index 未来继续动作的实际基础。

- 命中使用原 Worktree、Native Chat Tab ID、原生会话 ID、本机归属及当前内容组。仅附加标记且仍存在的本机对象使用开发预览路径。关闭的布局可通过「查找工作对象」再次打开。
- Enter 或点击后，命令面板关闭并将输入焦点交回原会话。原工作台的同一结构化 Chat 视图让出加载位置，回到 Worktree 时沿原身份重新呈现。草稿属于 Native Chat。
- 仍需查历史时保留 Vault 的明确入口；跨 Host、在线执行、审批和统一会话状态筛选继续验收。

源码为 `workspace-preview-navigation.ts`、`worktree-jump-palette-workspace-tab-row.tsx`、`use-worktree-jump-palette-selection-actions.ts`、`StructuredAgentSessionPaneOverlayLayer.tsx`。关联 C.10、E.01、R.03 与 J03/J05。

## 验收

从普通 Worktree 搜索有两个 Pane 的布局中另一项目 Chat，检查目的地、键盘后实际焦点、草稿、Workspace 身份和原工作台 Chat 挂载。关闭另一个工作空间后，验证该 Chat 仍能走普通 Worktree 路径。

交接沿用原生 Composer 的焦点请求。回放发现嵌入 Explorer 的列表会被误作焦点弹层。将嵌入用法标为页面内容后，常驻文件列表可继续浏览，同时命令面板退场可正常交接。 [结果行](evidence/iteration-12-14-windows/i13-location.png) · [交接过程](evidence/iteration-12-14-windows/session-to-workspace/timeline.json)
