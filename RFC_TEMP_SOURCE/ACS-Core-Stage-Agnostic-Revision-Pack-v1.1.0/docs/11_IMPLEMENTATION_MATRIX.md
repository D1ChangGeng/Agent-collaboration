# 11｜Codex 实施矩阵（阶段无关）

**判定方式**：逐项从当前源码和证据评估 `retained_verified / implemented_needs_evidence / partial / absent / incompatible / blocked`；绝不能从旧 WP 状态模板推断进度。P2 已存在成果保留，不作为 P0/P1 验收门槛。

| ID | 级别 | 类别 | 具体改造 | 旧 R 映射 | 最低验收 |
|---|---|---|---|---|---|
| C01 | P0 | correctness_guard | 通信核心/身份和回复不回归 | R-001,R-002,R-003,R-006,R-007,R-008,R-009,R-010 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C02 | P0 | capability_extension | Adapter 能力/证据声明 | R-017,R-039 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C03 | P0 | capability_extension | 最后输入准入 | R-015,R-016 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C04 | P0 | correctness_guard | Native 操作证据和未知调和 | R-004,R-005,R-011,R-012,R-013 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C05 | P0 | correctness_guard | 绑定代次与接收端 fencing | R-003,R-014,R-018 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C06 | P0 | capability_extension | 支持条件下的安全唤醒/延期 | R-020,R-029 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C07 | P0 | capability_extension | 受权 Session 续接与重新绑定 | R-019,R-036 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C08 | P0 | correctness_guard | 跨主机/混合版本/限额 | R-031,R-037,R-040 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C09 | P0 | correctness_guard | 安全迁移与历史保留 | R-035 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C10 | P0 | correctness_guard | 真实资格与原始证据 | R-038 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C11 | P0 | capability_extension | 最小只读诊断/受控恢复 | R-037 | 只读诊断/受权恢复/通知故障路径维持正确，个人 seen 的 T088 仍属 P2 可选；受控失败按原记录保存。 |
| C12 | P1 | client_service | 可信 HTTP facade | R-028 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C13 | P1 | client_service | 可重建 Conversation 查询 | R-021 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C14 | P1 | client_service | 客户端权限状态与技术状态 | R-030 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C15 | P1 | client_service | 一致快照与事件重放 | R-023,R-024,R-025 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C16 | P1 | integration_contract | NativeLink 和两源 provenance | R-027 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C17 | P1 | integration_contract | Orca-owned Receiver 最小端口 | R-032,R-034 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C18 | P1 | integration_contract | Orca Native delegate 合同 | R-033 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C19 | P1 | client_service | Headless 实际 ACS Client | R-033 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C20 | P1 | integration_contract | 完整 ACS 通信 UI 合同地图 | R-033 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C21 | P1 | correctness_guard | 客户端与宿主授权/来源隔离 | R-024,R-027,R-032 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C22 | P2 | optional_product | 个人已读与通知 seen | R-022 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C23 | P2 | optional_product | 个人草稿/偏好与静音归档 | R-022 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C24 | P2 | optional_product | 附件二进制服务 | R-026 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |
| C25 | P2 | optional_product | 全文消息搜索 | R-026 | 真实源码/必要回归/风险负例同时核验；无改造缺口可 retained_verified |

完整需求、真实源码复用项、测试编号和依赖在 `contracts/change-items.json`。

## 实施完成的真正判断

没有改动源码也可 `retained_verified`，条件是现有实现确实满足目标行为、受影响的安全回归与资格证据有效。反之，仅新增 API DTO/Mock 不算实现；能力 supported 必须有目标版本的真实证据。
