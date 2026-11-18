# ORCA 插件优先能力核查

核查日：2026-11-06。结论级别：官方源码与公开合同静态核查；没有安装/启动 Orca，没有连接模型、真实 Agent 或 ACS，没有执行真实消息发送。

## 结论

当前上游足以支持“先用插件验证组织、长角色资料、Skills 组织、消息入口”的方向。右侧原生 components panel 已有 Tree、Table、Tabs、Textarea、Markdown、按钮和持久化数据 API；缺少自定义顶部/左侧栏，不构成已证实的用户目标阻塞。需要先验证真实工作流中的可达性、切换成本和消息闭环，再决定是否存在值得 Fork 的缺口。见 P03–P04。

ACS Core 不是这些资料与入口的默认依赖：插件能在自己的存储中维护稳定角色 ID、职责、Skills 目录与工作空间/会话的绑定，调用原生 workspace/terminal/agent API。这个结论是能力组合推断，不是已经实现的插件或业务数据迁移。组织资料、业务授权、可靠通信和执行恢复是不同问题，不能用同一个“插件支持”结论概括。

没有现成的插件 Host API 可直接调用 native orchestration send/check/ask。官方源码明确将公共 Host API 与内部 runtime RPC 分开，内部注册表不暴露给插件；源码确有 Orca CLI 的 send/check/ask handler。可信 Node worker 通过受控 CLI 适配的路线有代码层可行性，但身份、端点发现、权限、消息消费、副作用、断线重试与版本兼容均待实际验证，不能写成“插件已集成原生通信”。见 P02、P28–P31。

## 基线与新增变化

固定比较：[9055eb9…52b8a24](https://github.com/stablyai/orca/compare/9055eb9344dac1300311337cb1f0040d8094e3c2...52b8a24d275fe0cb598abb54119426712fae7a70)。GitHub connector 比较结果为 ahead 5、behind 0、total commits 5；完整响应见 compare.json。

比较中没有插件文档、插件 Host API、贡献 schema、send/check/ask 实现的变更。通信邻近改动集中在 worker stop/release/federation stop receipt 和 terminal wait settlement，包含 workers.ts、worker-stop.ts、新增 single-worker-stop.ts/federated-worker-stop-host.ts/worker-stop-remote-receipt.ts、worker dispatch stop/start 和 runtime capabilities。旧 worker 停止/回收证据不能无检查地当作当前版本已验收。

本报告新增读取均固定到 52b8a24d275fe0cb598abb54119426712fae7a70。5 个已有 corpus 文件复用 9055…快照，因完整 compare 未列这些路径变更，适用于该 head：plugin-host-api.md、plugin-authoring.md、plugin-contribution-points.ts、plugin-panel-contribution.ts、project-group-types.ts。GitHub search 仅用于发现路径；它返回了旧索引 SHA 9fbad428…，没有用于证明当前内容。随后所用新文件均按固定 head 重新获取。

## 场景 → 合同 → 插件增量 → 运行待验

| 场景 | 官方可读合同 | 插件需要补齐 | 尚未验证的实际行为 |
| --- | --- | --- | --- |
| 组织树、角色、消息入口 | 右侧 panel 支持 HTML/components；原生 Tree/Table/Tabs/Input/Textarea/Markdown；P03–P04 | 组织/角色/收件箱数据模型、分页、导航与内容；可优先使用宿主控件 | 实际 sidebar 宽度、键盘、可发现性、跨工作空间切换、数据量/加载/错误/空状态。没有实机 UX 结论 |
| 长角色资料跨会话保留 | storage 共享于插件各 surface、写入自有磁盘文件；256 KiB/value、5 MiB/store、1024 keys；P23–P24 | 稳定业务角色 ID、映射与重新绑定；版本/冲突/迁移；不能把 terminalId 当永久角色 ID | 重启/升级/禁用/重装/损坏恢复；多端同步不是此 KV 合同 |
| 窗口与 workspace 上下文 | workspace.readContext；worker workspace.list/open；P01 | 将组织对象绑定真实 workspace ID/host；处理 null/truncated | 远程 host、folder/worktree、聚焦变化；readContext 没有通用项目资料/完整组织树 |
| 命令、快捷键、通知与摘要 | manifest commands/keybindings/statusBarItems；host statusBar.update/notifications.show；P01、P12 | 操作命令与摘要刷新；每项需声明/用户同意 | 菜单/快捷键冲突、平台差异；command replacement 超时会回退宿主，不能作为授权机制 |
| 启动与驱动原生 Agent | worker-only agent.launch、terminal.create/sendText/read；明确 workspace/terminal target；P01、P26 | role → harness/启动提示词/terminal 的绑定；展示可核验状态 | agent.launch 先返回 terminalId，prompt 异步提交，失败仅日志；不是 Agent 完成或消息已交付回执；read 是有限终端文本 |
| 生命周期 hooks/状态事件 | 8 hooks 已有 schema 与 hook chain；workspace/agent 四事件；P08–P10、P35 | 本地规则、提示词增强/拒绝策略、去重/重建；阻塞 guard 明确 onError:deny | 人手输入绕过 terminal/prompt hook；会话 restore 不触发 launch；agent.tool.before 仅本机 Claude Code 可阻止，其余观察；SSH/WSL tool hook 尚不支持 |
| 保存连接凭据 | 自有 secrets vault；缺 OS encryption 或 Linux basic_text 时拒绝写入；P25 | 使用 secrets API、错误呈现、轮换与作用域 | 各平台 keyring 可用性、注销/重装；这是静态保护，不是可信 worker 对同 OS 账户的完整隔离 |
| 调用 native send/check/ask | 公共 facade不暴露 raw RPC；CLI handlers 调用真实 orchestration methods；P02、P28–P31 | 受控 CLI argv/JSON 适配、身份/连接发现、请求标识、消费/peek/ack 约定与错误恢复 | plugin worker 没有天然 orchestration caller；ORCA_* 被 env allowlist 剔除；不能借别的 pane 身份；所有实际通信闭环未测 |
| Skills 资料组织与原生 Skills | 原生有 skill inventory；CLI install/update 针对 bundled registry；P32–P33；插件 contributes.skills 仍空槽 P07 | 插件可存 Skills 元数据/角色关联并呈现，或在批准的 FS 流程中衔接原生技能；不能称为现成插件贡献点 | 用户自定义 Skills 的发现、目标 harness/项目选择、安装/更新与实际加载；bundled CLI install 不能被夸大成任意包安装 |
| 原生 MCP 配置 | 上游有 MCP config candidates/inspection；P34；contributes.mcpServers 保留空槽 P07 | 按原生 harness 配置衔接；该能力不要求先保留 ACS Core | 配置存在不等于 Agent 实际加载/授权/调用；插件没有公开 MCP 注入 Host API，按 harness 实机另验 |
| 复用现有 groups | 原生 ProjectGroup 有 id/name/parentGroupId/order/collapse/color 等；P27 | 可先保留原生 workspace 组织，插件组织层绑定其对象 | 此类型存在不证明公开插件 groups CRUD；本次公共 API 表无该方法，不能默认可操作原生 group registry |

## 强制保障的边界

- **Host API 入口有实质强制**：逐次校验 method、surface、当前 consent/capability、严格 params；mutation 先写 attempt audit，写不成就拒绝；作用发生前复查当前安装/manifest/approval；P15–P17。该保证适用于这些宿主入口。
- **可信 worker 不是权限沙箱**：它是单独 Node 进程，fork 不带 Node permission flags；node: 内建按普通 Node 加载；公开称 full-access。能在宿主 OS 账户权限内访问 FS/网络/子进程是此执行模型的含义；能力清单不会约束其直接 Node 调用。不能把 storage:own/secrets:own 误写成对 full-access worker 的 OS 隔离；P12–P14、P19。进程崩溃隔离与访问权隔离不能混为一谈。
- **worker 有有限纵深防护**：环境变量白名单剔除 shell/CI credentials 及 ORCA_*，清除父进程 execArgv，启动/重启检查批准内容与当前同意。它们减少误带凭据和未批准代码执行，不保证抵御已批准恶意 worker。OS/网络/文件策略仍会影响实际能力。
- **UI frame 的边界更强且不同**：桌面 isolated guest 有自有 partition/process/origin，no Node，并在 Electron session 层封网络、proxy、DNS/WebRTC/permissions；components panel 同样运行 hidden sandbox guest；P18。浏览器客户端采用较弱 srcdoc 路线，不能将 desktop 的保障外推到所有端。
- **hooks 有范围与失效语义**：默认失败放行；可 onError:deny，但仅对当前仍参与的阻塞 hook 生效，已禁用/移除插件不再代表用户；P35。它不构成所有 harness、用户手输、session restore、所有主机路径的统一授权边界。
- **常驻不等于持久服务**：hooks/statusbar 插件被预热并免空闲回收；其他 worker 按 command/event/request 懒启动，idle 可停；worker 进程/协议/lifecycle 仍 experimental，可随时停。storage 在磁盘，内存与正在等待的命令/event 不持久；不能据此承诺外部消息队列、跨机 Inbox 或 exactly-once；P20–P24。
- **Core 保留仍开放**：若未来确定需要现有 ACS 的认证、可信调用者绑定、独立持久 Inbox、跨端授权/撤销、断线续接等语义，需逐项比较 Orca 原生语义与受控适配实测结果。资料存储和入口本身不产生保留 Core 的必要性；缺公开 Host API 也不自动推出 Fork 必须。

## 文档冲突

plugin-authoring.md 第700–714行把 hooks 与 skills/mcpServers 等放在 planned contribution points 内。当前同一 SHA 的 generated manifest 将 hooks 定义为真实贡献，源码 contribution-points.ts 154–158 实际加载 hook schema，plugin-hook-contribution.ts 定义8种事件，plugin-host-api.md 279–294 描述行为，plugin-hook-chain.ts 有强制实现。当前应采用 schema/实现/生成 API 合同；不能沿用 authoring 尾段得出“hooks 尚不可用”。实际 reserved 是 agentHarnesses、skills、mcpServers、taskSources、connections、sidebarCards。

## 验证与交付边界

本次验证包括：GitHub official compare、固定 SHA 文件读取、必要路径索引、来源/行号与本地快照检查。没有运行 Orca 或原上游 schema parser；本地没有该项目 node_modules/zod，未为研究安装依赖。也没有运行上游测试，源码中的测试文件名只表示可追加验证入口，不能写成测试已通过。

交付：本报告、source-index.md/source-index.json、compare.json、sources/ 官方证据快照、source-manifest.json（本地文件 hash 与来源）。没有修改产品源码、管理记录或真实运行配置。

