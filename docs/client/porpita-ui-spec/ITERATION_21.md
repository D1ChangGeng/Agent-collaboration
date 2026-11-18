# 第 21 轮：把不同 Host 的会话带进同一工作空间

目标是在同一条工作流里比较两个会话的进度，并把输入交给具体来源。第 20 轮已核对同名历史在目录中的 Host 标签。这一轮把该识别方式带到「选择会话」、工作空间 Pane 标题和窄窗的「切换窗格」。本机和配对 Runtime 的会话继续由原 Native Chat 呈现。

查看了之前的两块本机 Chat、目录中的同名会话及 Host 标签。VS Code 编辑器组提供同窗分割的参考，JetBrains Gateway 的独立连接说明了另一种按来源回到工作的组织方式。对于两个来源需要反复对照的任务，采用前者的同窗分割关系，沿用 Porpita 已接受的 Split、单 Pane 窄窗和 Host 标签。每个 Pane 的连接及操作范围由自己所属的 Runtime 确定。 [双 Pane 基线](evidence/iteration-09-11-windows/i9-two-worktrees.png) · [目录基线](evidence/iteration-20-loopback/i20-directory-hosts.png) · [VS Code 编辑器组](https://code.visualstudio.com/docs/editing/getting-started/userinterface#grid-editor-layout) · [JetBrains 多连接](https://www.jetbrains.com/help/idea/work-inside-remote-project.html#create-multiple-connections)

「新建工作空间」选择第一条已开 Chat 后，可用「添加会话」选择另一个来源。列表沿用目录的准确标题、项目、Host 和实际可用性。输入焦点由已选择的 Pane 接管，窄窗切换保留两个引用。目录、工作台搜索和 Vault 的原位动作继续通过同一来源检查，已打开对应工作空间时进入原 Pane。

会话与布局均以 Host、配对版本、Worktree 和原生会话 ID 定位。本轮场景是同名、同 Provider 历史 ID、不同原生会话 ID。实际原生会话 ID 或工作树归属有冲突的对象暂不能加入，原工作树组件的草稿与文件路由还需各自明确来源。直接 SSH、跨设备授权边界和超过两个 Pane 的组合保留各自的验收。 [来源规则](WORKSPACE_INTERACTION_SPEC.md)

中英文回放均通过正常 Tab 操作建立同名标题，随后验证两边的原记录和独立草稿。600×460 下只有选中的 Pane 显示，焦点移到对应的输入框。目录选中 Studio 后返回同一 Workspace 和原 Composer。 [宽窗](evidence/iteration-21-23-loopback-zh/i21-mixed-workspace.png) · [窄窗切换](evidence/iteration-21-23-loopback-zh/workspace-host-short-switch/timeline.json) · [目录重开](evidence/iteration-21-23-loopback/i21-reopen-from-directory.json)
