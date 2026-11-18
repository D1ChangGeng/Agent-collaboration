# 第六轮 · 从工作台搜索进入会话历史

从 Sidebar 打开跳转面板，输入一段会话标题。已经打开的聊天仍可直接回到原工作位置。需要查旧会话时，选择底部的「搜索会话历史」，当前词进入右侧历史面板，搜索框取得焦点。用户在原项目查看搜索结果，再以 Vault 的定位或恢复动作决定如何继续。

## 设计决定与实现

第五轮已有可以处理多个 Host、撤回、离线重试的 Vault，跳转面板的「已打开的聊天」空态只提示新开聊天。将 Vault 命中直接并入跳转结果会把导航和恢复混在同一个键盘默认动作中，还要重复维护来源、授权、索引进度与二级动作。把查询交给更适合持续浏览的工具是比较过的另一种路径。IntelliJ Search Everywhere 提供将搜索继续带到 Find 工具窗的入口。Porpita 沿用 Orca 跳转面板、ghost Button、Vault 结果和工作台 Dock，将入口置于面板底部已有的辅助操作区。 [第五轮](ITERATION_05.md) · [IntelliJ Search Everywhere](https://www.jetbrains.com/help/idea/searching-everywhere.html)

- 单击、Enter 或 Space 启动该命令。点击的是转交查询，现有方向键、Enter 选择结果及 Escape 返回各自保留原行为。按键事件在命令面板层识别焦点所在按钮，避免被选中结果的 Enter 处理接走。
- 入口出现在能显示 Vault 的工作台。跳转面板在 Skills 等暂时没有右 Dock 的页面继续用于其他导航；创建工作树阶段也由原创建视图掌管 Dock 位置。
- 转交内容为当前输入去除首尾空白后的值。Vault 选择「全部」工作区范围，并沿用用户当前历史 Host、Harness 和索引设置。空输入打开浏览列表。搜索词的传递只供 Dock 消费，Settings 启动同一入口时可保持既有查询，`/resume` 弹窗继续使用自己的输入。
- 激活命令后移除跳转面板的退场遮罩，将焦点交给可操作的历史控件。复用既有窄窗栏位分配与历史标题筛选。Host 失败和恢复依据第五轮已有反馈。

主要源码为 `worktree-jump-palette-surface.tsx`、`use-worktree-jump-palette-controller.ts`、`right-sidebar-state.ts`、`use-ai-vault-search-focus-request.ts` 与 `AiVaultSidebarPanel.tsx`。同一轮增加 11 个既有语言目录的按钮文案。

## 验收

| 路径 | 通过条件 |
| --- | --- |
| 开聊空态到历史 | 当前项目存在合成 Codex 历史，跳转面板查不到已开聊天时可转交搜索。Vault 通过实际历史扫描找到旧标题 |
| 键盘交接 | 原输入传递，搜索框取得焦点，当前工作树及内容标签保持 |
| 窄窗与空输入 | 600×420 CSS px、减少动态时查看同一路径。打开空查询后能浏览原历史 |
| 没有 Dock 的页面 | Skills 保留普通跳转。历史交接动作按页面能力隐藏，Escape 回到当前页 |

回放使用现有隔离 Electron 工具 `node tools/observe-installed.cjs <输出目录> --related-index`，依第五轮设定源码、入口和 Electron 路径。使用 `--related-baseline` 在第五轮构建截取对照。

Windows 英语浅色与简中深色各通过五步。焦点指的是后台 Electron renderer 的 DOM 焦点，历史来自合成 Codex 记录。Space 与 Enter 共享实际处理路径；最终归档的键盘交接使用 Enter。 [基线](evidence/iteration-06-baseline/run.json) · [英语](evidence/iteration-06-windows/run.json) · [简中](evidence/iteration-06-windows-zh/run.json)

这是统一 Session Index 的入口衔接。持续的 Sidebar 会话目录、三轴状态组合、直接打开到目标 Workspace 和分组规则继续在 C.10、R.03 和 [对象交互](WORKSPACE_INTERACTION_SPEC.md) 中推进。
