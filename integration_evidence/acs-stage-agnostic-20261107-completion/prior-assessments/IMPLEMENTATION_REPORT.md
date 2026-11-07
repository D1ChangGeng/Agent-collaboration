# ACS Core v1.1.0 实施结果（当前增量）

整体仍在开发；当前CLIENT_P1_CONTRACT_READY=true（v1.1通信服务/委托合同范围），CORE_P0_QUALIFIED=false、ORCA_HOST_QUALIFIED=false。逐项机器状态以 `adoption-state.json` 为索引。

最新增量为原 Message 条件唤醒，详见 `message-wake-20261107/REPORT.md`：最终PG220通过/2跳过，组件888通过/14条件跳过，两个捕获源范围前后不变；897个PG源文件再次与当前字节匹配。以下rebind批次保留其历史范围，不代表最新所有字节。自然消息初始准备/ready续行已实现，停止进程的同Session自动恢复及实际Native/Orca资格仍未完成。

## 0. 版本与实际代码

源码仓库 `D:\Chatgpt\Agent-collaboration`，分支 `codex/core-cleanup`，HEAD `19d7881d49ee887315c54c5bc02e0cc424061376`，HEAD tree `8856b23e59d50eccb1198475e84937c48a71b0bb`。源码元数据版本 2.3.1，实际运行/安装版本另行验证。工程包含未提交改动和新文件；HEAD 不能代表本批代码。当前逐文件 SHA-256 见 `rebind-20261107/receiver-rebind-pg-20261107b.json`，跟踪文件 diff digest 与只读 Git 观察见 `source-after-rebind.json` 和 adoption-state。

运行环境为当前 Windows 工作区、既有本地 WSL PostgreSQL 测试容器及本机 HTTP/TLS。用户已授权隔离测试。未执行生产或真实 Native/模型操作；实际 Orca Host revision、插件权限及接通状态未验证。未假设旧包工作阶段，既有成果和失败证据保留。

## 1. 范围变化与成果保留

| 原条款/工作面 | 本版范围 | 当前动作和证据 |
|---|---|---|
| R-019/R-036，C07 Session 恢复/绑定 | P0 | 增加显式 ready-target rebind；保留原恢复操作、原 issuer/Outbox/未知结果；E-RECEIVER-REBIND-PG-73 |
| R-020/R-029，C06 唤醒/延期 | P0 | 保留有界自然消息维护，已接受 prepare/resume/rebind 自动续行；自然消息派生安全 wake 仍待完成 |
| 通信 facade、事件、来源链、Host port | P1 | 保留22操作、59 DTO 和真实 headless 消费证据；26 GWT 精确审计继续 |
| 附件、草稿、个人状态、搜索等 | P2 可选 | 保留既有实现/历史回归与数据；本轮不扩展其范围 |

完整旧 R/T/UI/API 映射沿用修订包 contracts 与 adoption-state；用户的 README、管理设计、研究/UI 和其他工作树内容未回滚。

## 2. P0：独立 ACS Core

可信身份、稳定 Slot/Client、显式 reply_to、message_only、wait、非消费 read、历史权限保持现有分层。Native ACK、模型输出和显示状态不等于 Agent 回复。

已有 Adapter/Driver describe、当前 observe、最后准入和原操作 reconcile 保留；签名生命周期接入实际 Core/Node/DriverJournal/TLS。busy/approval/draft/unknown 不自动穿透；可能 Native 副作用只查原操作，不能重放或新建替代 Session。

当前 rebind 在原 Command/Outbox 冻结同 Slot/Scope 的源/目标与团队状态，重新鉴权和验证目标签名 ready 事实，持有 Slot/Endpoint/团队锁原子发布新 epoch。旧未知 Message/Attempt/许可保留原目标；旧执行被拒绝，原历史读取仍可按当前 read 权限继续。原命令可由维护器续行；没有第二套账本。

当前 E2 73项和 E1 884项结果见第5节。四项 TLS 用例是已有 prepare/原 ACK 回查链路；新增 rebind 的容量事实受控，不能代表真实 Node/Harness rebind。原消息条件初始准备/ready续行已有当前证据；停止进程的同Session恢复、当前真实 Codex/OpenCode/多主机断连恢复及独立回复资格未齐。

`CORE_P0_QUALIFIED=false`。

## 3. P1：ACS 通信客户端服务

22 个必需 operationId 已有实际 OAuth/HTTP/SSE/PG/SDK headless 消费证据，非仅 OpenAPI 声明。独立 P1 consumer 的 P2 调用/写入0、Native 输入0。事件 snapshot/replay/撤权及 MCP/HTTP 同调用者、普通角色拒绝等证据分列在 `source-link-20261107/`、`p1-exact-20261107/`。

Conversation 为只读通信投影，Message/显式回复关系不由 Native 文本推断。可选 SourceLink 按原 Core receipt→Attempt→handoff/DriverJournal/协议证据定位，当前参与者 ACL 和原 provider admission 包围只读访问；本机公共接口已挂载，远端原始 journal reader 尚未接通。NativeLink 当前关联与历史 SourceLink 分开。

Orca 集成采用稳定授权 port，保留 typed unavailable/host_extension_required；当前受控 Host delegate 不是实际宿主。26 GWT 和 UI01–UI30 范围仍依据机器映射审计，尤其 T082 子 Agent 源块、T063/T064 实际原子单输入 owner/双 adapter 竞争未获得真实 Host 证据。没有新建 Orca UI 或接管模型/工具/Diff/审批。

`CLIENT_P1_CONTRACT_READY=true`（限定v1.1本机服务/委托/降级合同）；`ORCA_HOST_QUALIFIED=false`。当前156项P1/210项SDK、22实际操作、26场景与30行矩阵退出审计见p1-current-20261107/REPORT.md；实际Host需要对应扩展和独立资格。

## 4. P2：已有/未实施

read/unread、draft、preferences、search、binary attachments、notification seen 等沿用已有实现及各功能证据；生产部署和完整可用性不由本轮推断。本轮不增加这些功能，不删除既有实现，也不以其未完成项阻塞 P0/P1。当前组件包含附件输入/通信合同等必要安全回归，其余历史批次保留各自源范围。

## 5. 测试与失败

| 等级/当前批次 | 结果 | 原始证据 |
|---|---|---|
| E2 实际隔离 PG，部分本机 TLS，Native 受控 | 73通过，0失败/跳过，665.18秒；894捕获文件不变 | `rebind-20261107/receiver-rebind-pg-20261107b.json/log/xml` |
| E1 当前组件/合同/crypto/SQLite/工厂 | 884通过、14条件跳过，171.70秒；源码不变 | `rebind-20261107/core-current-rebind.json/log/xml` |
| E2 初轮，加入 Slot 并发保护前 | 44通过，212.01秒；894文件不变，仅为历史范围 | `rebind-20261107/receiver-rebind-pg-20261107a.json/log/xml` |

73项分为18 rebind、28原恢复、10维护、12 executor、4原 Core/TLS/Node、1团队回归。命令、时间、逐文件 hash、机器范围和 runner 全部归档；两批次不能拼成一次全量资格。14跳过按协议、平台、缺 PG 和真实 Native/模型 opt-in 分列。Ruff 针对修改文件通过。

本轮无失败；此前配置、传输时限、OAuth 状态及测试夹具的失败与复测历史保留在原目录。E0 静态合同、历史 E2 43/102/7 与 SDK190 等记录不能替代 E3 真 Native 协议、E4 独立模型通信或 E5 实际 Orca Host，后三者当前未宣告完成。

## 6. 数据迁移与回滚

本次 rebind 无数据库 schema delta，使用原恢复 Outbox 的封存目标和生命周期状态。旧无封存目标的恢复命令继续 unsupported，不能补造原授权。既有 DriverJournal schema2 仍需显式 adoption；不隐式创建/迁移缺失私有 namespace。

完整发布失败回滚、原未知消息/Attempt 字节保留、旧许可失效和历史 read 继续已有实际 PG 测试。没有生产备份恢复或切换，也未重放任何可能发生过的 Native 副作用。混合版本/缺 transport 继续明确拒绝。

## 7. 无法验证和外部缺口

当前没有真实 Native 进程/模型/宿主资格。默认 WSL PATH 只读观察找到 `/usr/local/bin/codex`、未找到 OpenCode；未检查所有安装位置，不能据此断言 OpenCode 未安装。实际版本、生成 schema、私有账号/Provider 授权及独立回复链尚待建立。

Orca 原子 input owner 扩展、实际 Host 和远端原始 journal reader 仍未资格化。原未知投递保持未知，不因 rebind 被标为成功。本地 C06 和 P1 精确场景工作仍可继续，这些缺口不构成停止全部开发的理由。

## 8. 交付与下一步

代码与证据保留在当前工程分支，未提交、未 Push，未 merge/tag/release/部署。接口与运行说明见 `docs/runtime/RECEIVER-EVIDENCE.md`、`docs/runtime/COMMUNICATION-CLIENT-API.md` 和 `docs/client/`；测试可由同目录 runner 在明确隔离环境中复现，连接秘密仅在运行时注入。

原消息条件唤醒已接入，下一项为 P1 精确场景与矩阵验证；并行的证据任务为补 T082 源块及核对26 GWT、明确 T063/T064 的 Host gap，再完成实际 Native/独立 Agent/Orca 资格。详细接续入口为 `CURRENT_TASK_STATE.md`，机器状态为 `adoption-state.json`。


最新P1精确增量：`p1-precise-20261107/REPORT.md`记录4项实际PG/OAuth/TCP/SDK通过，补T041完整空视图链、T060缺字段provider观察事件、T082受控子Agent源块/child ACL。生产实现未变，897路径前后不变；首轮夹具字段错误保留。实际Host与矩阵行审计仍需独立结论，三个里程碑继续false。


最新矩阵witness：`ui-contract-evidence.json`覆盖30行scope/authority原映射；17个服务来源行由实际22操作consumer记录、9个Host行通过18项delegation/deny/unsupported测试，SDK208项全通过，真实服务consumer1项通过。P2四行保持可选。详情 `p1-ui-matrix-20261107/REPORT.md`，实际Host/各场景语义按其限定独立，不冒认UI或E5。


最新P1合同退出：`p1-current-20261107/REPORT.md`、`p1-exit-audit.json` 与h批次156通过/0跳过、SDK210通过绑定当前源码。C12–C21旧partial/未执行描述已存history并按真实服务/受控委托合同纠正。Host缺口不阻塞v1.1合同，但不等于实际Host支持；P0真实Native/恢复/独立Agent仍未资格化，目标未完成。


2026-11-07 08:37 JST：用户明确允许的实际Codex0.166无Session元数据探测已完成一次，三个只读RPC成功，自有WindowsJob树已停，Session0/prompt0，哈希pin匹配。见native-metadata-probe-20261107/RESULT.md。此只证明实际CLI元数据和清理，不是接收/恢复/模型资格；原批准阻碍仅对该次解决，不扩大后续范围。
