# 09｜工程验收、正确性测试、完成定义

## 测试层级不可互换

E0 `package_static`（包合同一致性）；E1 `unit`；E2 `controlled_integration`（真实 PostgreSQL、HTTP/stdio/多进程，有标注的 Adapter double）；E3 `native_protocol`（真实安装 Harness、Session 与接收器）；E4 `independent_agent_e2e`（两个独立模型自主通过 ACS 完成关联回复）；E5 `orca_host_integration`（实际 Orca/插件 Host 真实接通）。每条证据同时写源码 SHA、执行工具/版本、OS/主机、授权模式、命令、退出码、原始记录和限制。E0–E2 不能冒充 E3–E5。

## 分别宣告三种状态

- **`CORE_P0_QUALIFIED`**：P0 所有目标不变量已测试，已声明的 Native 组合有对应资格、blocked 的未覆盖组合列清楚；旧 ACS Core 独立运行不用 Orca。
- **`CLIENT_P1_CONTRACT_READY`**：P1 必需操作、领域授权与事件、headless ACS client 和 NativeLink/Host bridge contract 已可运行并通过测试；不包含 P2 产品特性。
- **`ORCA_HOST_QUALIFIED`**：仅在实际 Orca 版本/Host API 与 ACS Receiver 端口、单输入 owner 和 NativeLink 通过真实测试后才可宣告。若公开接口不足，`CLIENT_P1_CONTRACT_READY` 可成立但 `ORCA_HOST_QUALIFIED=false/blocked`。

## 测试优先级与旧 T 编号

`contracts/scenario-scope.json` 是 v1.0 的 96 个 T 的重分类，不重写它们的 Given/When/Then；旧包测试内容可继续复用。P0 先跑既有不变量与实际 Native 故障窗口；P1 跑授权 HTTP、conversation、cursor/事件 snapshot race、NativeLink 与 headless；P2 仅在功能已实现或单独选择交付时执行。**P2 已存在代码的安全回归不因优先级降低而删除。**

## 支持资格与阻塞表达

目标未安装或真实凭据不可用：标 `blocked`（无资格），不伪造通过；未实现的 P2：`out_of_scope_now`，不是 P0/P1 失败；已实现但未取得证明：`implemented_needs_evidence`；证据来自旧版本且代码/受影响配置变更：`stale_evidence`，需受影响测试重新验证。

## 最低实际链

P0：已安装 Codex ↔ OpenCode 的实际发信、可靠原生输入、独立 Agent `reply_to`、wait 断线恢复、message_only 零 Native、旧绑定拒绝、Provider ACK 未知不盲重。受控故障用于难以人为稳定触发的竞态，但不能冒充真实 Provider。P1：实际 HTTP profile→contact→conversation→message→delivery→snapshot/replay→revocation→host port unavailable→typed fallback 的 headless consumer。

## 性能与预算

确认有界输入、分页、消息内容、状态探测、重复通知及保留策略，不强迫统一 p95/吞吐 SLA。性能结果必须来自实际测量；长期大规模负载未测试不能称 qualified。避免因引入实时事件而阻塞既有 Authority commit 或导致跨 Project 侧信道。

## 完成报告

依 `handoff/FINAL_REPORT_TEMPLATE.md` 输出分段状态、gap mapping、实际代码路径与提交、原始命令/日志/失败/复测、数据库迁移、Host gap，以及仍需用户授权的事项。勿因无法运行 Orca Host E5 而否认已经通过的 ACS P0，也勿用 P0 通过代替 P1 客户端就绪。
