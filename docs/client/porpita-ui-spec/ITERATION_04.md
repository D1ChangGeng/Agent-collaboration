# 第四轮 UI SPEC · 从历史继续原会话

用户在 Vault 找到会话后，可以读历史、回到已存在的输入位置，或显式恢复已关闭的会话。这个路径接续第三轮的「已打开的聊天」搜索，覆盖历史与实际工作的交界，见 C.10、E.01、F.01、G.06、O.modal.agent-session-history、R.03 和 T.04。

## 设计决定

Porpita 现有历史列表同时承担查阅和继续，行标题点击展开详情，跳转和恢复在悬停时并列出现。在同标题、不同会话 ID 的本地 Codex 记录里，基线的已打开行同时提供了两个动作。Zed 的线程列表单击即切换，适合以会话作为主要导航对象。VS Code 把查询历史与打开可继续的会话分开，并在多个输入面共享会话时明确当前写入方。Vault 同时保有来自多个 Harness 的记录，因此本轮沿用行标题的查阅动作，将既有继续动作常驻行尾，复用 Orca 的 ghost Button、LocateFixed、Play、Tooltip、详情和菜单。 [基线](evidence/iteration-04-baseline/i4-history.png) · [Zed 线程历史](https://zed.dev/docs/ai/parallel-agents#thread-history) · [VS Code 会话管理](https://code.visualstudio.com/docs/agents/run/sessions/manage-sessions)

| 条件 | 行尾首要动作 | 选择后的结果 |
| --- | --- | --- |
| 原 Native Chat 已打开 | 跳转到原始窗格 | 用历史的 Host、工作位置和结构化 ID 选择原 Tab，交回 Composer 焦点 |
| 唯一原 Terminal Pane 可定位 | 跳转到原始窗格 | 用 Harness、原生会话 ID、Host、Tab/leaf 以及已知来源路径校验。复用原终端选择和输入焦点 |
| 原 Pane 已关闭，现有恢复路径可用 | 恢复 | 走既有 Harness 恢复路径。普通记录使用终端，Native Chat 自有记录使用其 Host 的结构化会话路径 |
| 来源不全、匹配歧义、只读或恢复受限 | 查看详情、可用时显式恢复 | 相同标题和提示词仍可用于查找。运行状态和原 Pane 跳转依赖确切的目标。恢复由既有来源、Host 和权限检查决定 |

首要动作以 Orca 原按钮尺寸常驻。点击行标题及详情按钮继续查阅，菜单提供等效动作，键盘沿用原焦点与恢复弹窗规则。终端的恢复拖放随终端原位跳转收起，原 Native Chat 的拖放沿用结构化会话揭示。显式 fork 或交接从既有菜单发起。原 Pane 已消失时显示原有无法定位反馈，用户留在历史列表。交互沿用现有终端焦点提示及减少动态设置。 [工作对象](WORKSPACE_INTERACTION_SPEC.md) · [视觉交互规范](VISUAL_INTERACTION_SYSTEM.md)

## 验收边界

1. 隔离档案以实际 Codex JSONL 扫描展示两条同名记录。查看把状态留在列表，点击恢复才启动原有流程。
2. 原终端的历史记录显示定位，只读、未打开或仅提示词匹配的记录保持各自可用动作。测试覆盖同 ID 跨 Host、同 ID 不同路径、同 Host 重复 Pane、原 leaf 移除与旧数字 leaf。
3. 键盘定位原终端，鼠标定位已恢复的 Chat，分别核对原 Tab、leaf 或 Composer。提供方身份撤回后，该行即时退出原位定位。
4. 在 Windows 浅色英语和深色简中比较常规窗与窄窗留白、标题截断、输入/Tab 焦点和减少动态条件。跨设备请求、登录后回复和 macOS/Linux 继续按 J03、J05、J06、J12、J13。

## 源码与复现

`AiVaultSessionRow` 和 `SessionRowTrailingActions` 复用现有历史列表。原位定位由共享的 Vault Pane 索引、Workspace owner 和 Tab/leaf 校验接管。Native Chat 走已有结构化 Tab 激活；历史恢复沿用运行端的来源检查、准备和恢复操作。在恢复请求准备期间，同一个历史行的重复激活复用当前请求。

设置 `ORCA_BACKGROUND_LAUNCH=1` 和 `VITE_EXPOSE_STORE=true`，以 `electron-vite build --outDir out --mode e2e` 构建隔离 Electron。运行 `node tools/observe-installed.cjs <输出目录> --session-history`，指定 `PORPITA_SPEC_SOURCE` 和 `PORPITA_SPEC_ENTRY` 为源码树，`PORPITA_SPEC_EXE` 为该树锁定的 Electron。单独输出的构建也可将 `PORPITA_SPEC_ENTRY` 指向该构建的 `main/index.js`。基线使用 `--session-history-baseline`，简中深色设置 `PORPITA_SPEC_LOCALE=zh`。

回放使用隔离 Git 项目和 Codex 历史，Windows 窗口保持后台隐藏。终端运行状态由夹具通过 Renderer 的状态入口送入，历史扫描、选择、Tab、PTY 和焦点为实际客户端行为。证据中的命令、会话载入和模型回复分别以对应结果判定。

## 回放结果

- 两个同名历史条目通过 Vault 原查询与详情验证。打开详情保留终端数量，来源身份恢复后行尾重新提供定位。 [初始列表](evidence/iteration-04-baseline/i4-history.png) · [常驻动作](evidence/iteration-04-windows/i4-actions.png) · [查询](evidence/iteration-04-windows-zh/i4-search.png)
- 进入已有终端时，Enter 选回相同 Tab/leaf 并将焦点交给对应 xterm。Native Chat 从已有菜单导入原对话，离开后再次定位同一结构化会话，Composer 获得焦点且草稿保留。 [终端回放](evidence/iteration-04-windows/return-to-terminal/timeline.json) · [Chat 回放](evidence/iteration-04-windows-zh/return-to-chat/timeline.json) · [聊天截图](evidence/iteration-04-windows-zh/i4-chat-original.png)
- 另一条已关闭记录走终端恢复，重复点击只增加一个标签，界面显示会话已排队。该项验证客户端启动，CLI 加载对话、登录后发送和模型回包待验。 [终端启动](evidence/iteration-04-windows/i4-resume-terminal.png)
- Native Chat 的 `/resume` 弹窗携带查询并聚焦搜索框。方向键与 Enter 选择当前会话后，弹窗关闭，焦点回到同一 Composer。 [简中弹窗](evidence/iteration-04-windows-zh/i4-resume-picker.png) · [返回断言](evidence/iteration-04-windows/history.json)
- 英语浅色、简中深色各通过 11/11。常规窗 1280×800，窄窗 860×520 开启减少动态。53 项聚焦测试、Renderer 类型检查与差异质量门通过。 [英语过程](evidence/iteration-04-windows/run.json) · [简中过程](evidence/iteration-04-windows-zh/run.json) · [源码身份](SOURCE_BASELINE.md#第四轮来源)
