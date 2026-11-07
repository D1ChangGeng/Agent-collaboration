# v1.1.0 范围修订与当前增量

采用输入：`RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/`。
原包50份有效载荷及 manifest 的校验通过；这是 E0 包完整性，不能替代产品验收。
原始开发包保持不变。源码基线为 `19d7881d49ee887315c54c5bc02e0cc424061376`，
分支 `codex/core-cleanup`，本地工作树包含用户原有改动和本任务未提交成果。

| 旧范围 | 本版范围 | 当前处理及证据 |
|---|---|---|
| WP00–WP10 线性全量验收 | C01–C25 按实际缺口与依赖推进 | `adoption-state.json` 接续实际源码，不从 WP00 重做。旧日志与失败历史保留。 |
| WP07 附件和 NativeLink 同一门槛 | NativeLink=P1；二进制附件=P2 | NativeLink 继续补足真实 OAuth/SDK 验收；已有附件源码、迁移、授权和测试保留。 |
| 35个 HTTP 操作全部必交 | 22个 P1、13个 P2 | 完整 OpenAPI 逐项标注 `x-acs-tier`；`communication-p1-openapi.yaml` 为可再生成的 P1 子集，保留兼容的可选数据。 |
| 已读、seen、偏好、草稿、搜索 | P2 非阻塞 | 保留已实现行为；停止扩张产品范围，共享代码变更仍需安全回归。 |
| 单项 headless 通过作为完整客户端证据 | 独立 P1 API/事件/Host降级链 | 原生产 SDK 实际 TCP/SSE 测试7项通过，但依赖 P2；仍需独立 P1 consumer，不能据此宣告 Client P1 完成。 |
| 完整 Orca 原生界面/控制接入 | P1 稳定受信端口；E5 Host单列 | 采用已有签名 Receiver 验证器及独立 Host 授权；缺少原子输入 owner 扩展时明确不可用，不通过普通 mutation RPC 绕过。 |
| 已有恢复领域服务等于 HTTP 能用 | 真实挂载、鉴权、操作回执和 SDK | 发现未挂载的 `recoverReceiver`，补上 facade 和 POST202；继续复用原 command/Outbox，只推进原 operation。 |

本次 P0 修正：bootstrap lifecycle helper 只接受 `spawn`/`close`。
未知动作曾错误借用 close 身份，现在在读取身份或调用授权前拒绝。
这不代表已实现独立的管理 resume/rebind 生命周期执行器。

本次 P1 修正：恢复请求的身份来自现有受信 caller，OAuth 的 prepare/resume
还须具备 `runtime.invoke` scope；提交前失败保持 none，提交后观察失败保留原
operation。潜在副作用按 unknown 保留，不因 HTTP 重试生成另一原生操作。
HTTP 使用 body 的 `expected_revision` 和显式 Idempotency-Key；不接受 If-Match 替代。

初次新增范围/恢复/生命周期纯测试59项通过，见 `pure-recovery-scope-isolated.json`。
后续补齐分页token32项、显式DriverJournal基础及审查修正后，最终274项组合通过，
Ruff通过；见 `current-pure-contract-lifecycle-postreview.json`、原始日志和JUnit。
前后源码指纹未变。初次257与独立77专项的记录单列保留，不互相替代。
含旧 ASGI suite 的较大尝试在默认沙箱50秒超时，原日志 `pure-recovery-scope.log`
保留，不能写成完整通过。

原先11项NativeLink因两次自动审批审核超时及默认沙箱限制未启动的记录保留。
2026-11-07用户已明确允许隔离测试；同一既有本地容器/本机HTTP范围内，实际
NativeLink11项、独立P1的22操作链、4类分页63项已分别通过。初轮401/403分类错误、
测试Unicode请求头、wait结果投影503的失败及修正日志均单列保留。
每轮固定855路径+helper=856项字节前后不变；新未挂载生命周期代码明确排除，
不能以这些E2结果冒充当前整个工作树或Native/Host资格。

`CORE_P0_QUALIFIED`、`CLIENT_P1_CONTRACT_READY` 与 `ORCA_HOST_QUALIFIED`
分别记录。当前均不宣告完成；受控集成不代替真实 Harness、独立 Agent 或 Orca Host。
没有生产迁移、部署、推送、合并、PR、Tag 或发布。


2026-11-07 生命周期接入封存：启用的 concrete factory 延迟创建 Native Session，
签名链复用既有 TLS Receiver、Core recovery operation/Outbox 与 DriverJournal。
configure_team 在事务外推进同一 executor，未启用目标仅观察已有状态。
新私有预留窗口由操作者选择1–30秒；已存在的 Native 输入状态沿用原始时效。
历史 ACK 可以在 Driver/Node 重构后从保留 journal 读取；丢失原始创建行保持 unknown，
过期发证保持原 deferred operation，均不另建命令或重放 Native。

当前证据分列：组件881通过/14跳过，实际PG45通过，最终PG/TLS/Node19通过。
每次运行各有源码清单与前后校验，不能拼为一次全量通过；详细记录见
`lifecycle-20261107/wiring-checkpoint-20261107.json` 和各原始日志。
P1 的原始消息 SourceLink 公共接入、26场景映射仍未关闭；实际 Native/模型/
独立 Agent/Orca Host 资格保持单列。整体三个里程碑继续为 false。


2026-11-07 SourceLink公共接入：既有readMessage增加严格可选来源查询，不新增P1操作；
原Core dispatch receipt定位attempt，当前参与者权限与registry身份包围只读journal。
NativeSourceLookup/SourceLink/NativeSourceSession为显式追加合同，59模型和22个P1操作。
当前43项PG/OAuth/HTTP/SDK兼容、210项组件合同、190项SDK分别通过；P1场景组合102项
通过且888捕获路径不变。原始Given/When/Then保留在26项映射中，缺精确证据条目未冒认通过。
本机来源链已经挂载；远端journal reader、实际Native/Orca资格及若干P1精确用例仍单列。


2026-11-07 ready-target rebind：复用原 recovery Command/Outbox，封存同 Slot/Scope 的明确目标，
以签名 ready 观察和原 issuer 当前授权发布新 epoch、退休源。原未知输入/Attempt/收据不迁移；
Slot 锁保护并发插入，团队配置在等待后重验目标；事务失败完整回滚。没有新 Native rebind action、
spawn/resume/input permit、账本或数据库迁移，prepare 仍是独立明确授权。

当前73项隔离PG组合全通过（含4项原Core/TLS/Node链路回归），894捕获文件不变；
组件884通过/14条件跳过。新增rebind本身使用受控签名容量，真实Node/Harness/模型/Orca资格未完成。
详见 `rebind-20261107/REPORT.md`、`IMPLEMENTATION_REPORT.md`。C06自然消息派生wake与P1精确审计继续；
三个整体里程碑保持false。用户原有修改和P2保留，未提交/Push/部署。


2026-11-07 原消息条件唤醒：实际Message Command/operation/Outbox是唯一来源，显式双侧开关、当前授权和正面容量下才准备。没有恢复命令、第二消息/账本或启动ACK转消息ACK。未知只读回查，过期/丢invoke阻止输入，活动wait/message_only不唤醒，历史阻止namespace再建。最终PG220通过/2明确跳过、897路径不变；组件888通过/14条件跳过；失败历史分列保留。停止进程同Session恢复和实际Native/Orca未资格化。详见 message-wake-20261107/REPORT.md。
