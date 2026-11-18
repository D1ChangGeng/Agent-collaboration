# 第五轮 UI SPEC · 跨 Host 搜索与恢复

用户在同一个历史列表中查找本机和已配对 Runtime 的记录。即使标题、Harness 原生 ID 相同，也能辨认记录来源。主机断线时，仍可读取已搜索到的记录，了解漏搜的范围，并在恢复连接后用同一查询再试。

本轮承接第四轮的历史继续动作，范围是 Vault 的「所有主机」搜索、回源和失败恢复。直接 SSH 的全文索引、跨 Host 工作空间布局、全局 Session Index 保持在现有实施队列。 [第四轮](ITERATION_04.md) · [实施顺序](DECISIONS_AND_SEQUENCE.md)

## 设计决定

在第四轮基线，两个 Codex 索引可以返回同标题、同原生 ID 的记录。Studio 停止后，唯一结果失去来源徽章，失败提示显示配置 ID，余下游标通过「加载更多」呈现。 [双来源基线](evidence/iteration-05-baseline/i5-two-sources.png) · [断线基线](evidence/iteration-05-baseline/i5-unreachable.png)

参照 VS Code 将 Host 选择与连接分开，沿用 Porpita 的 Host 菜单和工作台。Elastic 的跨集群搜索允许返回已查询来源并报告跳过的来源，提供了部分结果的行为对照。一种做法是统一提示连接失败并把用户引到服务器设置，适合配对或权限需要修改的情况。已配对端暂不可达时，把配置名和重试放在结果上方，用户仍能留在原搜索完成本机部分。复用 Orca 历史搜索状态栏、`Button outline/xs`、`WorktreeHostContextBadge`、虚拟列表和工作空间激活。 [VS Code 主机管理](https://code.visualstudio.com/docs/agents/run/remote-agent-sessions#host-management) · [Elastic 部分结果](https://www.elastic.co/docs/explore-analyze/cross-cluster-search)

| 条件 | 用户可见行为 | 源码责任 |
| --- | --- | --- |
| 所有主机搜索返回一个或多个来源 | 每条结果显示该 Host 的现有名称。窄 Dock 优先保留来源与首要动作，时间、消息数进入详情 | Vault 行与既有 Host badge |
| 一个来源不可达、索引未就绪或游标过时 | 其余匹配仍在列表中，状态区显示来源和原因，提供「重试」 | all-host 合并、每 Host 结果与原搜索状态栏 |
| 当前范围只在断线 Host 有匹配 | 空列表显示具体未完成来源，可在原查询重试 | 原搜索状态栏 |
| 游标仅用于重试不可达来源 | 显式重试发起当前查询第一页，「加载更多」用于仍有可继续读取的搜索页 | all-host 游标与 Renderer |
| 多记录共享原生 ID | 命中详情优先匹配明确的 Host、Harness、ID、记录路径和已知 Codex home。只有唯一对应的脱敏记录可借用预览 | 结果转投影、会话历史详情 |
| Host 配对标识变化 | 旧请求结果和对应会话引用退出当前搜索，依新配对身份取结果 | 搜索身份与既有主机订阅 |
| 所属配对端发布 Chat | 恢复后选中已发布的原 Chat。用户已经换到另一个工作位置时保持新选择 | 结构化恢复回执、Host 快照与现有 Tab 激活 |

重试沿用已有就地查询，等待期间保留同一查询的已知结果，重试控件暂禁用，键盘焦点回查询字段。新的查询、Host 范围、索引规则或配对身份使用新结果。缺失或无法核对的记录显示来源状态，历史详情使用当前结果证据。输入和启动沿用已有 Host 权限检查。

## 验收

- 本机和 Studio 分别用独立的应用档案和 Codex 索引，Studio 在回环端口运行真实配对服务。两条记录使用相同原生 ID 与标题，各有独立对话与项目。
- 从 Vault 选择「所有主机」并搜索。看清两条同名结果的来源，展开 Studio 的记录，核对详情指向 Studio。
- 停止 Studio，回放同一查询，核对本机记录可见、来源名与重试路径。仅 Studio 可命中的查询汇报未搜索来源。重启 Studio 后通过同一配对重试，保留查询并找回结果。
- 在常规窗和窄窗核对来源名称、结果行和焦点，查看至少一段连续回放。使用英语浅色和简中深色。

## 复现

在隔离 Porpita 工作树用 `ORCA_BACKGROUND_LAUNCH=1`、`VITE_EXPOSE_STORE=true` 构建 e2e 版。用 `node tools/observe-installed.cjs <输出目录> --host-search` 运行，指定 `PORPITA_SPEC_SOURCE`、`PORPITA_SPEC_ENTRY` 与锁定的 `PORPITA_SPEC_EXE`。同源基线用 `--host-search-baseline`，简中深色用 `PORPITA_SPEC_LOCALE=zh`。

脚本创建临时 Git 仓库与合成 Codex 记录。扫描、索引、查询、配对认证与断线来自实际 Windows 客户端和服务进程。全部运行在同一物理 Windows 主机。服务端使用回环监听，配对材料只在测试进程之间使用。

## 回放结果

- 两个独立索引返回同标题、同 Codex ID 的两条记录。展开 Studio 时读到 Studio 的原对话。撤回其夹具源文件后，刷新只保留本机匹配。 [同名结果](evidence/iteration-05-windows/i5-two-sources.png) · [撤回来源](evidence/iteration-05-windows/i5-source-disappears.png)
- Studio 停止时，本机结果保留来源标签，「未搜索」显示 Studio 配置名。仅 Studio 可命中的查询保留漏搜提示。Enter 重试沿用查询，焦点回搜索框。Studio 以同一配对身份重启后，原查询重新返回记录。 [断线](evidence/iteration-05-windows-zh/i5-unreachable.png) · [键盘重试](evidence/iteration-05-windows-zh/i5-retry-offline.png) · [连接恢复时间线](evidence/iteration-05-windows/retry-host/timeline.json)
- 从历史恢复 Studio 记录后直接选中其 Native Chat，显示 Studio 的对话。切到本机后点击历史行的定位按钮，回到配对端的同一 Tab 和输入区，保留未发送草稿。 [回到原 Chat](evidence/iteration-05-windows-zh/i5-return-chat.png) · [焦点回放](evidence/iteration-05-windows-zh/return-to-studio/timeline.json)
- Windows 英语浅色和简中深色各通过 9/9，含 860×520 CSS px 减少动态场景。46 项聚焦测试、Renderer 和主进程类型检查、变更质量门通过。测试档案未登录 Harness，未向模型发送内容。跨物理机器、直接 SSH、配对权限变更及 macOS/Linux 继续按矩阵验证。 [英语](evidence/iteration-05-windows/run.json) · [简中](evidence/iteration-05-windows-zh/run.json) · [版本](SOURCE_BASELINE.md#第五轮来源)
