# Codex 主执行说明：交付 Porpita 初代完整桌面应用

你的任务是实施本包，交付真实可安装、可使用的 **Porpita**。不要把输出停在研究报告、开发计划、接口、单独 Core、截图、插件面板或未打包的开发服务器。

## 0. 已确定的产品决策

Porpita 以 Orca 的现有完整桌面产品为基线。保留其原生 UI、信息架构、Native Chat、工具/审批/Diff、编辑器、终端、工作区、Harness 运行及已有远端能力。ACS Core 取代产品正常路径中的 **Agent 间通信**。用户与 Harness 的原生交互和宿主执行控制不是要删除的通信模块。

Project/Root/Route/AgentSlot 是内部组织与路由模型，不是新主导航设计依据。初代只增加完成真实使用所需的少量入口，并复用现有组件。不得先制作一个 ACS 管理控制台。

最终品牌为 Porpita。插件可以用作内部组织手段，但无须先完成一个独立 Orca 插件产品；必要的薄 Host 扩展直接在派生代码内实现。

## 1. 先读取

按顺序读 `docs/00_PRODUCT_AND_SCOPE.md`、`01_BASELINES_AND_ADOPTION.md`、`02_TARGET_ARCHITECTURE.md`、`03_COMMUNICATION_REPLACEMENT.md`、`04_HOST_RECEIVER_AND_SESSION.md`、`05_ONBOARDING_CORE_LIFECYCLE.md`、`07_NATIVE_UI_REUSE.md`、`13_FUNCTIONAL_ACCEPTANCE.md`、`14_WORK_PLAN.md`。需要时查其他文档与任务文件。

`contracts/source-lock.json` 记录核查基线；`references/SOURCE_MAP.md` 标记哪些路径已读、哪些仅定位、哪些必须在实施时重新发现。路径移动时按符号查找，不猜测宿主公开 API。

## 2. 从任何现有开发状态接续

检查当前 ACS 与 Porpita/Orca 的 HEAD、工作树、已实现功能、可用构建环境和原始验收记录。保留已有修改、证据、分支、数据；不 reset、不强制覆盖、不重跑全部旧工作包。`tools/inspect_workspace.py` 可帮助只读记录，但不强制使用。

对每项能力记录：reuse / complete / adapt / missing / blocked，附实际路径即可。已有且正确的实现直接复用；只补缺口。比参考 SHA 更新的代码不要回退。将实际采用的两个提交和本地改动写入 `handoff/BASELINE_LOCK.json` 的工作副本。

这一步是启动开发的一部分，不是独立的预研、PoC、架构重审或等待批准阶段。

## 3. 直接实施

按 `tasks/WP00` 至 `WP09` 的依赖连续推进。每阶段都产出代码或可运行应用增量。并行允许，但共享 Native Session 只能由现有宿主调度输入；不要另启 ACS Driver 争抢同一会话。

优先打通：安装/启动 → 打开仓库 → 启动原生 Agent → 受信注册到 ACS → Agent A 发信 → 宿主把消息交给 B → B 原生工作 → B 用自身 ACS 身份 reply_to → A 收到 → 用户在原生界面看到结果与执行过程。

之后覆盖原有消息入口、结构化协作兼容、已有 P2 体验、重开和远端。普通通信无需 Run/Task；保留的 Run/Task/Dispatch/Gate 属于宿主可选工作流，其消息运输也使用 ACS。

## 4. 约束实现方式

- 不复制原生 Chat/Transcript/Tool/Approval 数据库到 ACS。不建立第二份 Agent 消息权威或平行队列。
- 复用 `sdk/communication-client.ts` 及已采用 DTO。不要照旧开发包再生成一套协议。
- 实际接通 `runtime/orca_receiver_backend.py` / 既有 Receiver 路由和宿主输入 handover；不能以 Host double、`terminal.sendText` 或接口存在代替正常链路。
- 既有校验允许合并/删除重复层。判断依据是正常路径清晰、真实功能有效、必要测试通过，不是防御项数量。保留真实身份、正确目标、不误报提交状态的最低语义。
- 完整移除正常路径的上游 A2A 消息发送/消费/唤醒权威；保留原生用户输入和进程控制。不得静默回退到旧通信后端。
- 用户界面不得要求填写 Scope、Grant、Epoch、消息句柄等内部字段。必要权限与模式通过已有设置/选择器呈现。
- 保留上游版权与第三方许可；不批量替换 wire 枚举、数据库字段、插件兼容命名或外部 Harness 身份。
- 不使用 Orca 的发布凭据、遥测收集、更新服务或品牌专属云作为 Porpita 自有服务。按品牌清单处理，保留无关第三方集成。

## 5. 明确完成的含义

首代默认以 Windows x64 可安装构建为必须交付。该平台选择是包的实施默认，并非用户声称已完成平台决策；如果已有有效 Porpita 首发目标，以现有事实接续并明确记录，不暗中缩小范围。macOS/Linux 源码与构建入口继承保留，在实际有 runner 的平台执行构建，不用交叉编译证明实机体验。

普通用户无需 Python、Node、pnpm、Git checkout 或手动建 PG 库才能启动客户端和本地 ACS。托管本地 Core/依赖与已有服务连接都需通过 UI 完成；模型账户/许可证由用户提供，不伪造凭据。

最终必须在实际打包安装的 Porpita 中运行双 Agent、原生工具/审批、消息/回复、退出重开等场景，保留最小充分的录屏/截图和对应运行日志。功能本身的实测通过即可；不扩展为所有罕见平台/故障组合的研究。

不能把 `unsupported`、跳过、Host stub 或静态截图作为首代必须功能通过。遇到环境/凭据阻塞，可以完成其他开发并交付候选，清楚列剩余阻塞；不得把候选标记为最终验收通过，也不得无限扩展范围。

## 6. 交付

输出 Porpita 源码提交、必要 ACS 增量提交、Windows 安装产物及哈希、运行说明、实际功能验收记录、品牌/服务出口清单与第三方声明。填写 `handoff/DELIVERY_REPORT.md` 和按 schema 生成的 `delivery-manifest.json`。`tools/verify_delivery.py` 只能查记录/文件的完整性，不替代人工或真实应用验收。

没有用户额外授权，不创建公网发布、购买签名服务、迁移生产库或覆盖原 Orca 安装/配置。内部本地候选可完成安装验收；是否签名与是否公开发行分别记录。

完成标准是 `PRODUCT_ACCEPTED`：应用能安装启动、正常原生功能保留、所有正常 A2A 入口转到 ACS、实际双 Agent 闭环可用、用户无需管理底层模型。`PACKAGE_VALIDATED` / `BUILD_OK` / `CORE_READY` 都不是这个结论。
