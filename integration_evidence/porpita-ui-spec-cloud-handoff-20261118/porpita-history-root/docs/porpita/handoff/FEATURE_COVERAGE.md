# Porpita 功能范围

代码归属和 11 安装版实测记录。

| ID | 功能 | 实现 | 安装版证据 |
| --- | --- | --- | --- |
| F01 | 窗口/侧栏/Tabs/Panes/分屏 | 原工作台、侧栏、标签与终端 pane | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F02 | 主题/design tokens/快捷键/焦点 | 原主题和键位设置，工作区选择器 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) · [installed11-stock-ui-comparison.json](../evidence/20261109/installed11-stock-ui-comparison.json) |
| F03 | 仓库/工作区/Worktree | 原工作区 Git Host 和新建控件 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F04 | Native Chat及流式历史 | 原 Native Chat 与会话 journal | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F05 | 工具/思考折叠/后台任务 | 原流式工具卡片与实际 Shell | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F06 | 原生模型/参数/权限选择 | 原 Harness 模型、参数和权限 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F07 | 原生审批和问题 | Host 原生审批及问题处理 | [installed11-agent-question-approval.json](../evidence/20261109/installed11-agent-question-approval.json) · [installed11-native-approval.png](../evidence/20261109/installed11-native-approval.png) |
| F08 | stop/queue/steer/compact等原生操作 | Host 负责队列、Stop、Steer 与 Compact | [installed11-agent-question-approval.json](../evidence/20261109/installed11-agent-question-approval.json) · [installed11-agent-question-core.json](../evidence/20261109/installed11-agent-question-core.json) |
| F09 | 终端/TUI/会话切换 | 原 ConPTY 终端和切换布局 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F10 | 文件树/Monaco/预览 | 原文件树、Monaco 和预览 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F11 | Git/Diff/stage/commit | 原 Git Diff、Stage、Commit | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F12 | 内置浏览器/设计工具 | 原内嵌浏览器 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F13 | Provider登录/已有插件/设置 | 原 Provider、插件与设置入口 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| F14 | ACS服务首次启动/连接 | 托管 Core 引导与已有服务登录 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-fresh-managed-setup.json](../evidence/20261109/installed11-fresh-managed-setup.json) |
| F15 | Agent稳定身份/上下文 | 自动建立可信 Agent 与项目联系地址 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-identities.json](../evidence/20261109/installed11-native-identities.json) |
| F16 | 真实宿主消息接收 | 原始 ACS 交付和实际 Host Native admission | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-local-native-readback.json](../evidence/20261109/installed11-local-native-readback.json) |
| F17 | 联系人/消息/关联回复 | 协作面板、联系人、原消息与显式回复 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-local-native-readback.json](../evidence/20261109/installed11-local-native-readback.json) |
| F18 | 实时消息和分页历史 | Core 分页、实时事件和快照 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-collaboration.png](../evidence/20261109/installed11-collaboration.png) |
| F19 | 私人阅读/通知seen | 真实私人阅读与通知状态 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-collaboration.png](../evidence/20261109/installed11-collaboration.png) |
| F20 | 草稿/偏好/静音/归档 | Core 草稿和用户偏好 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-reopen-after-reinstall.json](../evidence/20261109/installed11-reopen-after-reinstall.json) |
| F21 | 正文搜索 | Core 字面正文搜索 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-collaboration.png](../evidence/20261109/installed11-collaboration.png) |
| F22 | ACS附件及Host材料化 | Core 文件和接收 Host 物化 | [installed11-attachments.json](../evidence/20261109/installed11-attachments.json) · [installed11-group-and-attachment-core.json](../evidence/20261109/installed11-group-and-attachment-core.json) |
| F23 | 查看消息对应执行 | 原 Native 输入和消息来源跳转 | [installed11-native-target-source.json](../evidence/20261109/installed11-native-target-source.json) · [installed11-retained-core.json](../evidence/20261109/installed11-retained-core.json) |
| F24 | Run/Task/Gate可选工作流 | 原 Run、Task、Dispatch 和 Gate 生命周期 | [installed11-paired-worker-completion.json](../evidence/20261109/installed11-paired-worker-completion.json) · [installed11-paired-worker-exchange.json](../evidence/20261109/installed11-paired-worker-exchange.json) |
| F25 | 群组/远端通信 | 作用域群组与配对 Host | [installed11-group-gate.json](../evidence/20261109/installed11-group-gate.json) · [installed11-second-host-ready.json](../evidence/20261109/installed11-second-host-ready.json) |
| F26 | 重开/恢复/导入 | 原 Native journal、Core 续接和显式导入 | [installed11-service-reconnect.json](../evidence/20261109/installed11-service-reconnect.json) · [installed11-reopen-after-reinstall.json](../evidence/20261109/installed11-reopen-after-reinstall.json) |
| F27 | 安装/升级/卸载/并存 | 独立 Windows NSIS 安装及数据保留 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-uninstall-reinstall.json](../evidence/20261109/installed11-uninstall-reinstall.json) |
| F28 | 品牌/外部出口/法律声明 | 独立品牌、服务配置、CLI 和许可 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-brand-scan.json](../evidence/20261109/installed11-brand-scan.json) |
