# 10｜旧 WP00–WP10 到本版能力项的迁移对照

旧包的工作包 ID 保留用于追溯，但**不再是必须依次执行的线性作业表**。当前状态由源码/证据决定。下表和 `contracts/change-items.json` 同时使用。

| 旧 WP | 新版 P0/P1/P2 归属 | 接续规则 |
|---|---|---|
| WP00 基线 | P0/P1 横向保护 | 每次代码版本变化刷新必要事实，不重做研究报告 |
| WP01 身份/能力 | P0 | 已有授权不变，新增/完善 capacity/observation 的真实缺口 |
| WP02 投递账本 | P0 | 优先复用旧 operation/Outbox/Node Journal，不造新账本 |
| WP03 Codex/OpenCode | P0 | 对支持的实际版本只做 adapter 收敛、准入、故障资格 |
| WP04 唤醒/恢复 | P0 | 只实现有证据可安全做的唤醒/恢复；不能假重试 |
| WP05 客户端查询/个人状态 | **P1 通信 query + P2 个人状态/搜索** | 分拆，不以 read-state/draft 阻塞 conversation API |
| WP06 事件与同步 | P1 | 保留 snapshot/replay/权限；个人 read/draft 事件属于可选 P2 |
| WP07 附件与 NativeLink | **P1 NativeLink + P2 附件** | 明确拆成不同交付，不让附件拖慢 Host 接入 |
| WP08 Orca headless | P1 | 真实 ACS client、宿主 port 与缺口声明；UI/Fork 不在本轮 |
| WP09 迁移/运维/回归 | P0/P1 随修改做 | 不等 P2 完成后才允许单独验收 |
| WP10 交付 | P0/P1 分别签署 | 非 P2 失败不得被产品增强任务误报阻塞 |

## 机器合同引用规则

旧版 `R-001..040` 和 `T001..096` 保留原 ID 与原意；本版 `contracts/*-scope.json` 增加 tier。旧包 `contracts/openapi.yaml`、`models.schema.json` 可作为具体接口参考；**若本版 `api-scope.json` 标 P2，即使旧 OpenAPI 声称可用也不必在本轮实现**。不要擅自删掉已实现端点，仍需兼容。

## 最小示例

如果 Codex 已完成 WP00–WP04 且在 WP07 编写附件：立即检查 P0 是否有可验收证据；将已完成的 P0 标 verified；P1 继续实现 UI 必需通信服务/NativeLink；附件作为 P2 保留安全完整性，可暂缓进一步扩张。若 WP08 已开发 Orca Host bridge，应保留并核验单 owner、真实权限和 unknown receipt，不从零重做。
