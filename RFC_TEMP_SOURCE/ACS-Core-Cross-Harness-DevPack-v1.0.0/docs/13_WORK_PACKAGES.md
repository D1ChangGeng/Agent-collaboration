# 13｜连续开发工作包

按依赖执行，不设研究型前置关卡。每包必须落源码、测试与证据；遇到缺环境只阻塞对应资格，不放弃可做工作。接口/数据库/授权共享变更须串行集成。

## WP00｜基线与兼容护栏

依赖：无。

1. 记录实际 ACS/Orca revision、工作树、运行服务版本；不覆盖用户改动。
2. 定位 current send/read/wait/receiver/permission/schema/entry 调用链，保留旧 catalog 快照。
3. 把旧关键行为转为回归测试；记录当前支持矩阵与原始失败。

输出：`baseline.json`、`legacy-catalog.json`、`baseline-regression.log`。

退出条件：实际源码入口可定位，旧接口回归基线可复跑；不得停留在调研报告。

## WP01｜身份、能力与证据契约

依赖：WP00。

1. 实现统一 capability/observation DTO、证据时效与版本域。
2. 复用身份/授权/配置合并逻辑，建立 receiving epoch/generation 和只读状态投影。
3. 同步 schema、Domain、MCP/HTTP serializer，拒绝模型提供 sender。

输出：`capability-manifest.json`、`observation-auth-tests.log`。

退出条件：支持/当前可用/知识状态分离，Client/Slot/管理权限无回归。

## WP02｜投递账本与原生输入防重

依赖：WP01。

1. 扩展现有 operations/Outbox 实现 handoff intent、receipt、reconcile 状态。
2. 在事务里绑定消息、reply 索引、dedup 和 event intent；保持 per-Slot fence。
3. 覆盖 commit/dispatch/native ACK/进程崩溃边界，不持锁等待网络。

输出：`delivery-crash-tests.log`、`schema-delta.md`。

退出条件：同键原操作可恢复；未知输入不重复；合法回复不依赖 Native ACK。

## WP03｜Codex/OpenCode Adapter 增强

依赖：WP01, WP02。

1. 为实际两种 Driver 实现 describe/observe/admit/reconcile，按主机实际版本探测。
2. 实现 busy/approval/draft/ready 准入与最小上下文，禁用不支持的 steer。
3. 复用真实接收工厂与 Node 授权，不建立新任务执行器。

输出：`adapter-conformance.json`、`native-protocol-logs/`。

退出条件：两种既有主链通过；每项能力有版本和证据，unsupported 能安全留 Inbox。

## WP04｜唤醒、重连与跨主机恢复

依赖：WP02, WP03。

1. 实现 wait 结果通道与 wake 合并、失联 wait lease 调和。
2. 实现 resume/rebind/reconcile 管理动作；旧代次拒绝新副作用。
3. 增强 Relay peer capability/队列/ACK/错误隔离；保持 notice 向上语义。

输出：`recovery-traces.jsonl`、`cross-host-report.md`。

退出条件：断线恢复无重发；不抢审批/用户输入；未知状态如实保留。

## WP05｜客户端通信查询与个人状态

依赖：WP01, WP02。

1. 实现 OpenAPI profile/projects/routes/contacts/conversation/messages/delivery/wait/search。
2. 实现 conversation 可重建投影、显式 read frontier、preferences/draft CAS。
3. HTTP facade 与旧 MCP 共用领域服务/授权；UTF-8/多回复关系/分页无丢失。

输出：`http-contract-tests.log`、`query-authorization-report.md`。

退出条件：无 task 前置即可完整收发/查询；个人已读不冒充模型消费。

## WP06｜持久事件与一致同步

依赖：WP05。

1. 实现事务 event intent、snapshot high-water、SSE replay/断档/resnapshot。
2. 实时权限撤销、过滤/身份绑定游标、慢消费者背压、重连去重。
3. 实现 SDK/头部无界面 reducer，验证并发 snapshot race。

输出：`event-replay-traces.jsonl`、`revocation-stream-tests.log`。

退出条件：不丢 snapshot 窗口事件、不串权限、不以最新游标跳过缺失历史。

## WP07｜附件与原生关联数据服务

依赖：WP05, WP06。

1. 实现附件 staging/write/finalize/ACL/download/digest/清理及跨主机引用。
2. 实现 NativeLink 和双源 linkage，源权限不因关联扩大。
3. 实现 NativeViewProvider/CommunicationClient 类型与 delegate 操作边界。

输出：`attachment-tests.log`、`native-view-contract-tests.log`。

退出条件：附件可完整收发且不 SSRF/越权；原生 transcript 不成为 ACS 回复。

## WP08｜Orca 无 UI 集成接入

依赖：WP03, WP04, WP06, WP07。

1. 按固定源码映射 native Chat、source、status、plugin Host API；完成 UI feature manifest。
2. 实现 bridge/Orca-owned receiver 与 headless consumer，单一原生输入 owner。
3. 缺少公开接口时实现宿主端口合同、协议测试和最小 host-gap，不修改 UI/Orca 业务源码。

输出：`ui-readiness.json`、`host-gap-register.json`、`headless-integration.log`。

退出条件：所有 ACS 端点真实可用，所有原生功能有 delegate；宿主资格与 Core readiness 分开。

## WP09｜迁移、运维与综合回归

依赖：WP04, WP05, WP06, WP07, WP08。

1. 显式 additive migration/backfill/checkpoint/回滚演练，保留旧作者/关系/keys。
2. 服务/安装清单/observability/配额/健康与关闭 UI 后维护验证。
3. 执行旧 MCP、实际 DB、真实 Native、跨进程权限负例和并发回归。

输出：`migration-rehearsal.md`、`regression-matrix.json`、`installed-runtime-report.md`。

退出条件：迁移能恢复，旧客户端不回归；每个 claimed profile 都有真实证据。

## WP10｜交付闭环

依赖：WP09。

1. 核对全部 R/T/WP/UI feature，修复未闭环问题并保留失败记录。
2. 输出源码/测试/版本/实际资格/宿主缺口/安装使用说明。
3. 仅本地交付；不自动 merge/tag/publish/生产切换。

输出：`FINAL_REPORT.md`、`evidence-index.json`、`implementation-ledger.json`。

退出条件：达到 docs/00 的完成定义；未通过项明确阻塞，不伪造完成。

## 工程自主判断规则

模块路径变动、索引选型、具体内部类名由 Codex 根据实际源码决定并记入 ledger；不能通过“实现细节”改变权限、显式回复、未知输入、防重或任务解耦。必要的源码阅读与兼容探测在工作包内完成，不另开研究阶段。

完成旧能力回归之前不能删除旧路径；新能力 feature flag 默认关闭直至对应 gate 通过。需要性能优化时以 bounded fixture/load regression 验证资源界限，不宣称通用 SLA。
