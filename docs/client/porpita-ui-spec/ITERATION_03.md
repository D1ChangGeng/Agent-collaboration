# 第三轮 UI SPEC · 找到并继续已打开的聊天

## 阶段范围

用户在多个执行环境中工作时，可以用标题、工作树或项目名查找已打开的 Native Chat，选中后继续原聊天。保持现有 Sidebar 搜索、跳转面板、过滤和原生工作台。此轮是 Session Index 的第一条可独立验收的导航路径，对应 C.09、C.10、E.01、O.modal.worktree-palette、R.03、T.04 和 J03。

第二轮基线 `ac16c8eb3d901a5bd0b74d852afc4c634cb3eca1`，树 `3b70a60808e598d0e96297237232a173da667a90`。原隔离目录已不可用，基于同一提交建立 `codex/porpita-ui-spec-03`。现有产品文档及历史录像继续使用各自的版本记录。 [来源](SOURCE_BASELINE.md)

## 形态与取舍

- Porpita 的跳转面板具备聚焦输入、键盘选中、项目和 Host 过滤、结果行上下文与原 Tab 激活。Activity 的对象是事件线程，Vault 的对象是历史记录。前者通向对应 Pane，后者承担查历史、恢复与启动等动作。当前目标属于跳转面板。 [跳转](evidence/15-search.png) · [Activity](evidence/episode/35-activity.png) · [Vault](evidence/dock-panels/37b-vault.png)
- IntelliJ 的 Search Everywhere 把对象类别放在搜索框上方，保留名称和项目上下文。VS Code 的 Quick Open 使用输入前缀切换提供方，界面更省空间，体验依赖用户知道前缀。采用可见的「已打开的聊天」筛选，沿用 Orca 的面板、结果行和键盘，不增加一套搜索入口。 [IntelliJ 参考](https://www.jetbrains.com/help/idea/searching-everywhere.html) · [VS Code 参考](https://code.visualstudio.com/docs/editing/getting-started/tips-and-tricks#_quick-open)
- 筛选在打开的面板内生效，保留已输入的词。应用原有 Host/项目范围。结果提供现有聊天标题、Harness、项目和 Worktree；Host 只在有对应所有者证据时显示。同名结果按照现有 Host、Worktree、Tab 和 Pane 身份定位。

## 验收条件

1. 从 Sidebar 搜索打开跳转面板。选择「已打开的聊天」，键盘回到输入框。启用与关闭筛选保留当前输入，空结果解释当前范围。重新打开默认进入通用搜索。Windows 系统快捷键的窗口焦点条件另验。
2. 两个 Worktree 各开一个同名 Native Chat，使用实际可见的项目上下文区分。通过鼠标和键盘跳转两次，每次回到预期工作树、Tab 与输入区。重复选择复用同一个打开对象。
3. 查询无匹配、疑似 URL 或任务编号时，该筛选不执行对应的任务或浏览器操作，也不给出创建动作。复制含分隔符的完整聊天标题可精确命中。筛选切换前后的通用搜索仍可使用。
4. 在 Windows 1280×800 和 600×400 查看标题和上下文，检查中英、深浅与减少动效条件。使用实际应用和隔离档案，记录可见操作、结果和刷新范围。

后续 Session Index 仍须接入 Vault 历史、Terminal 中的 Agent 会话、稳定 Native Session ref、运行与通信状态、离线与权限，以及未打开会话进入目标 Workspace 的动作。Group Selector、跨 Project/Host 布局和 SidePanel 的验收照原顺序推进。 [完整交互规范](WORKSPACE_INTERACTION_SPEC.md) · [实施顺序](DECISIONS_AND_SEQUENCE.md)

## 实现与证据

- 查找入口复用 `WorktreeJumpPaletteSurface` 及现有 `Toggle`。索引复用现有 Tab 搜索，结果沿用焦点、排序、可读的命中片段和 Host/项目过滤。选项激活继续调用 `activateWorkspaceTabPaletteResult`，由工作台验证 Host、Worktree、Group 及 Tab，原生 Chat 的焦点由原有输入路径接管。
- 相同的 `Review` 查询在第二轮会呈现两个同名聊天、设置、动作和新建工作树。第三轮在聊天筛选只保留这两个聊天结果。在 600×400，标题与项目名各有位置，两个项目可直接区分。该分配沿用 Orca 现有来源标签，只在此筛选给项目名更多空间。 [第二轮对照](evidence/iteration-03-baseline/i3-same-name.png) · [第三轮英语](evidence/iteration-03-windows/i3-same-name.png) · [第三轮简中窄窗](evidence/iteration-03-windows-zh-final/i3-compact.png)
- 两个本地 Git 项目的 Native Chat 通过实际新建标签打开，各有未发送草稿。鼠标选中第一项，键盘 Enter 选第二项，再次打开第二项。每次都到相应 Worktree 的原 Tab 和 Pane，都是原 Composer 获得焦点，Tab 数保持为 2，两个草稿完整保留。按 Escape 关闭时，焦点回到发起搜索的 Sidebar 控件。 [导航断言](evidence/iteration-03-windows/navigation.json) · [按序截图与事件](evidence/iteration-03-windows/continue-open-chat/timeline.json)
- 前后两份证据均来自后台 Electron，启动档案、仓库和草稿均为临时数据，Harness 未登录。用屏幕截图及事件顺序核对过渡，采样不用于推断帧率。系统快捷键通过隐藏窗口的人工模拟未建立可靠证据。Enter、Space、Escape 及实际鼠标选中已在面板中验证。

### 复现

以隔离工作树构建 `electron-vite build --outDir out --mode e2e`，构建时设置 `VITE_EXPOSE_STORE=true`。运行 `node tools/observe-installed.cjs <输出目录> --session-search`。指定 `PORPITA_SPEC_SOURCE` 和 `PORPITA_SPEC_ENTRY` 为工作树，`PORPITA_SPEC_EXE` 为锁定的 Electron 可执行文件。设置 `PORPITA_SPEC_LOCALE=zh` 使用简中深色。脚本验证窗口隐藏，系统目录选择器仅返回临时仓库路径，其他导航和输入由可见控制执行。

英语浅色和简中深色各通过 8/8 步骤。新增文案覆盖 11 个内置语言目录，其余语言尚未渲染复验。Renderer 类型、格式、源码检查、变更质量检查和 80 项聚焦测试通过。源码通过提交钩子保存在本地 `272c1e9589`。 [版本](SOURCE_BASELINE.md#第三轮来源)
