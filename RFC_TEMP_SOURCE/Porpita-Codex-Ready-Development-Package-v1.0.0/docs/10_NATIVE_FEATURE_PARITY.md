# 10｜继承能力与功能完整性

`contracts/feature-parity.json` 是首代保留/接入清单。每行记录 upstream / Porpita owner、实际入口、复用或修改及验证结果。它不是要求新写一遍所有上游功能。

## 主要保留面

主窗口、主题、快捷键、侧栏、Tabs/Panes/分屏、工作区/Worktree、原生 Agent 创建/切换、结构化和 Terminal Chat、工具/思考展开折叠、文件/Diff、审批/问题、模型和参数、上下文/usage、历史与恢复、文件树/Monaco、Git stage/commit、终端/TUI、内置预览/浏览器、SSH/paired host、设置和插件接口。

使用现有 package scripts、stores、components、Host services；不要用静态样例替换。当前已定位 `src/renderer/src/components/native-chat/NativeChatView.tsx` 及 pane header/menu、file-drop 等；实际布局/store 路径由 WP00 在 adopted checkout 定位。搜索到路径不等于完整审查其实现。

## 不同 Harness 的实际差异

继承上游能力矩阵，而不是声称全部 Harness 完全等价。上游已具备的 Chat/工具/审批功能不得因 ACS 接入被关闭。ACS 托管接收尽量通过统一 Host 能力获得，而不是为每个 Harness 再写新 Driver。

首代真实协作重点验证 Codex 和 OpenCode；其它继承的 Harness 仍能正常启动/交互，采用其已有 smoke/回归和能力显示。某个提供者需要登录时说明操作，不假装已有账号。WSL/SSH 保持上游实际的 terminal-backed surface。

## 任务与编排

保留可选 Run/Task/Dispatch/Gate 的操作界面及工作控制，通信运输改用 ACS。任务实现可以保留内部 Orca 名称和表；它不是新消息权威。对外命令名称改为 Porpita，并更新对应 skill/preamble。默认普通多 Agent 通信无需启用实验性编排。

## 对完整性的限制说明

不可因为缺少上游专属云凭据而声称继承了其商业服务；也不能因此把所有本地功能缩减为演示。desktop 首代的核心范围必须真实可用。移动独立分发、所有第三方云组合与新增 Core 独立 Driver 不在首代新增范围；继承源码不删除。

## 性能

通信不进入 token 流逐 token 同步路径；不为每条可视消息启动新的观察进程；复用原生输入队列与分页/虚拟化。使用已有启动/输入/切换 benchmark 做同平台前后 smoke，出现肉眼可见卡顿或显著开销时定位改动，避免建立新的性能研究平台。

默认记录启动、输入响应和工作区切换的基线/候选结果。阈值沿用项目现有有效阈值；没有阈值时明确观察，不人为声称 SLA。测量用于纠正实际回归，不以大量指标延迟功能接通。
