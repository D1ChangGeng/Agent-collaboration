# Porpita UI SPEC 第二轮

本轮延续原 278 个条目，增加 7 个可追踪条目，覆盖 Linear 和 Jira 的条件界面、浏览器扩展弹窗、Linux 更新恢复与应用支持入口。首轮未归属的 91 个 renderer 候选已找到所属界面、运行职责或独立 Web 客户端边界。52 个主进程文件的 82 个原生调用也已绑定相关覆盖条目。 [覆盖矩阵](COVERAGE_MATRIX.md) · [Renderer 归属](source-index/module-coverage.csv) · [原生调用归属](source-index/native-host-coverage.csv)。

验收账面为 16 条本轮局部通过、5 条现版通过且目标待验、2 条夹具通过且集成待验、262 条继续按各自条件验收。首轮证据仍保留在原条目。 [核对报告](coverage-audit.json)。

## 工作台宽度

Windows 工作台已经使用同一预算计算左右栏。默认在 600px 及以上留出 320 CSS px 主区，左栏沿用 220–500px，右面板至少 220px，侧置 Activity Bar 占 40px。两栏并存的门槛分别为顶部 Activity Bar 时 760px、侧置时 800px。宽度更小时，保留最近明确请求打开的一侧，默认左栏。用户通过各自开关或工具快捷入口交换当前可见侧。自动收起保留用户记录的宽度和打开偏好，变宽时恢复；用户主动关闭的栏保持关闭。窗口放大缩小时不写入宽度偏好。高缩放下若 CSS 宽不足 534px，主区预算按当前宽的 60% 取整，紧凑工具栏和较窄 CSS 视口仍需实测。

| Windows 视口 | 左栏 | 主区 | 右栏 | 观察 |
| --- | ---: | ---: | ---: | --- |
| 1280×800 | 280 | 650 | 350 | 两个终端，各约 312px |
| 820×580 | 280 | 320 | 220 | 两个终端，各约 147px；旧安装版同条件主区约 190px |
| 820×580，侧置 Activity Bar | 240 | 320 | 260 | 右侧含 40px Activity Bar |
| 600×400，左栏 | 280 | 320 | 0 | Explorer 临时隐藏，焦点转移到可见的右栏开关 |
| 600×400，右栏 | 0 | 320 | 280 | Enter 打开右栏，焦点保留在开关；Explorer 名称筛选恢复 |
| 1280×800，恢复 | 280 | 650 | 350 | 双终端和两栏宽度恢复 |

这里的 320px 是整个主区。Windows 600×400 实测单个 Codex Native Chat 宽 319px，Composer 输入宽 281px。相同方向的两个 147px 终端可用于状态查看，长命令和 Chat 编辑需要更宽。集成 Workspace 时先沿用 Orca Pane 最大化，保留分屏树、比例和活跃输入。为新增的左右分屏预留至少 320 CSS px 给 Native Chat/编辑器，终端按至少 40 个当前等宽字符加内边距计算。上下分屏以可见 Composer 或输入行及状态区为下限。用长内容和字体缩放标定阈值。已有分屏不足时提供聚焦呈现和明确恢复入口，维持原分屏方向和 Session。 [Native Chat 回放](evidence/iteration-02-windows/i2-chat-narrow.png)。

当前临时收起保留 Explorer 局部查询。其他面板仍按原 Dock 生命周期和各自已保存的状态恢复。右栏暂保留零宽的结构节点，隐藏区域从键盘顺序移除。未来迁移的 SidePanel 必须为每种 Definition 明确保存的状态和恢复时机。宽度变化与拖宽即时反馈，已有比例拖拽和减少动效要求见 [共享规范](VISUAL_INTERACTION_SYSTEM.md) · [实际几何](evidence/iteration-02-windows/layout-measurements.json)。

## 浮层与关键操作

| 场景 | 已确定规则 | 验证状态 |
| --- | --- | --- |
| 阻塞工作区信任确认 | 信任标题、范围和两个明确动作可见；紧凑窗口可滚动，焦点留在决定面；Escape 与点遮罩都不作出决定 | 已在 Windows 600×400 验证两个动作命中；两条 toast 已在 DOM，Sonner 与通知卡片栈不可见。Enter 选择「让智能体询问」完成 |
| 其他安全 Dialog、平台认证、危险操作 | 活跃决定的说明和动作拥有焦点，发起者的错误和重试留在面内。若迁移到通知避让，先移入依赖 toast 的错误与进度，再开启避让。平台决定留在原生层 | 浏览器、插件、项目 Hooks、SSH、凭据和移除 Host 按独立场景待验 |
| Native Chat 审批或待输入 | 由原 Session 的消息区和 Composer 展示具体来源；其他视图只提示跳回。短窗弹出的消息不能挡住操作，打开辅助菜单后 Esc 返回原控制 | 原生审批历史和组件预览保留；不同 Pane 中并发审批待目标布局复验 |
| 普通 Dialog、Sheet、Popover、Context Menu | 保留现有层级和焦点返回。与 modal 动作相关的通知仍走原普通 Dialog 机制；菜单只由自己的锚点、选择和关闭规则控制 | 普通 Sheet 的旧 toast 提升、关闭及草稿保留有原组件回归 |
| 普通通知与提示 | 阻塞面存在时，低优先级通知可以延后展示，重要状态在所属区域常驻。关闭后才恢复仍然有效的通知，无焦点劫持 | 工作区信任在运行中显式抑制 Sonner 与卡片栈。计时继续，有限提示可能在关闭前过期；持久排队和过期策略留给后续统一实现 |

[信任窗口](evidence/iteration-02-windows/i2-trust-narrow.png) · [命中测试](evidence/iteration-02-windows/trust-measurement.json) · [普通 Sheet 回归](evidence/group-shape/ui__sonner--olderToastBehindModalSheet.light.png)

## 核心工作对象和当前边界

Group Selector 是下一阶段实现基准。试验复用 Orca 标签条、菜单和拖动传感器。每组按最近使用恢复活跃项，固定项与关闭动作留在组内。240 CSS px 下以打开列表补足横向溢出，宽窗延续相同位置与行为。移组在选择目的组后一次提交，Esc 保留源对象。完整规格和可回放对照见 [分组 Shape](GROUP_TRIAL.md)。

现有 split tree 的拖动入口按 `worktreeId` 校验，FileExplorer 的内容与请求由其 worktree 或 folder owner 解析。Windows 本次从实际入口接入第二个本地 Git 项目，与原 folder 工作区往返后可查看原变更。Codex Chat 通过已有分屏动作打开同工作树的终端。目标 Workspace 需要先实现独立布局记录，再将同一 Native Session ref 和固定 scope 的 Explorer 接入独立及嵌入宿主。以 J03、J04、J07 检查跨 Host/Project 同名来源、重复打开、原输入路由、移组、关闭、重开和不可用对象。 [交互规范](WORKSPACE_INTERACTION_SPEC.md) · [SidePanel 能力](SIDEPANEL_CAPABILITY_MATRIX.md)。

安装版 Candidate 11 两次在隔离档案启动本机托管 Core 后断开、重连。一次在原 Settings 页恢复「已连接」，另一次在原页等待 10 秒未见更新，重新打开后显示已连接。后一次状态变化的具体时点未测得。源码中 Settings 只在挂载和本地动作返回时更新状态，标题栏协作另有读取路径。设计要求两个入口读取同一连接状态，连接过程中显示明确的阶段，在请求返回后仍处于准备中时继续读取，直到成功或出现可处理的失败；读取与重试不清空草稿或重新投递。实际网络抖动与消息视图同步按 J09/J12 复验。 [连接回放](evidence/iteration-02-core/run.json) · [后一次测量](evidence/iteration-02-core/core-recovery-measurement.json)。

产品交付资料已推送私有仓库。Candidate 11 的源码树、安装器和 ASAR 已核对，重建 ACS wheel 得到相同 SHA-256。新版 Windows 修复的证据属于开发构建。macOS、Linux、Windows ARM64 与物理多机功能按各自资格计划验收。 [产品交付](https://github.com/D1ChangGeng/Porpita/blob/5e7ee4accd7a64965823573162479f9520da8ad4/docs/porpita/DELIVERY.md) · [平台资格](https://github.com/D1ChangGeng/Porpita/blob/5e7ee4accd7a64965823573162479f9520da8ad4/docs/porpita/PLATFORMS.md)。

## 源码集成状态

文档提交的 `check:changed` 3/3 通过。代码提交 `8040ab3a81` 的三项类型检查、变更代码检查、导入边界和聚焦回归通过。仓库级检查 24/32 通过，既有布局写入、React Compiler 和翻译检查仍有失败，广域相关测试到 7 分钟上限。后续提交 `ac16c8eb3d` 清理了 11 个语言目录各 12 个已退役键，核对了剩余文案。源码保存在本地 `codex/porpita-delivery-closeout`。原临时检查日志当前不可用，以上数字来自第二轮留存摘要。 [源码与证据身份](SOURCE_BASELINE.md#第二轮来源)
