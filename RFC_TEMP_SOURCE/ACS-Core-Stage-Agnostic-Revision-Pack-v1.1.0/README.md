# ACS Core｜阶段无关的范围收敛与实施修订包 v1.1.0

**用途：立即交给正在执行或准备执行上一版开发包的 Codex。** 无需用户告知旧包执行到 WP 几，也不需重启项目、回退提交或重新开展研究。此版本是**对执行要求和验收范围的修订（authoritative revision）**，不是 ACS 软件版本，亦不是已实施的源码。

## 一句话决策

保留 ACS 独立受信通信核心，优先增强真实 Harness 通信覆盖与正确性（P0），随后实现 Orca 可消费的必要 ACS 通信后端/宿主边界（P1）。个人体验扩展（P2）不再阻塞当前两个里程碑。**正确性不降级，实施范围适度减量。**

## 如何交付 Codex

1. 将此包放在 Codex 可读取处；提交 **`START_HERE_CODEX.md` 全文**。
2. 可以与上一版共存。上一版原始 ZIP 已附在 `reference/`，仅作为详细机器契约、旧条款和代码阅读目录。**不执行旧包 `START_HERE_CODEX.md` 中与本版冲突的全量必交要求。**
3. Codex 基于**当前实际仓库与证据**继续开发：已经满足的保留，部分完成的补齐缺口，尚未开始的按本版优先级实施。过去的 `not_started` 或 `passed` 模板不能替代当前观察。

## 文件结构

- `docs/`：范围权威、可接续实施、P0/P1/P2 的具体行为、正确性、Orca 源码吸收、交接、验收。
- `contracts/`：40 条 R、96 个 T、30 项 UI、35 个 API 的**新优先级映射**；独立可实施变更项；显式不变量与完成门槛。
- `tools/`：只读状态扫描、范围映射与包结构校验、SHA-256 验证。
- `handoff/`：一次性接续状态、偏差/证据、P0/P1 分别验收模板。
- `reference/`：上一版原始交付包及参考源码锁定信息。上一版中的 OpenAPI/Schema/Adapter Port 是**目标参考合同**，并非一律本轮强制实现。

## 权威优先级

当前用户明确要求与安全/授权边界 > **本包 `docs/00_GOVERNANCE.md` 和 `contracts/scope.json`** > 本包 P0/P1 正确性与资格要求 > 上一版对应详细契约（仅已激活条目） > 旧包执行计划与历史模板。

冲突时不猜测；Codex 在实施报告记录 `old_clause → revised_clause → affected_code → verification`，然后继续可实施工作；只有需要额外生产/真实账号/外部写入权限时才请求授权。

## 当前已核实的来源快照（不是执行时的源码版本）

- ACS：`D1ChangGeng/Agent-collaboration` 参考 `19d7881d49ee887315c54c5bc02e0cc424061376`，README/pyproject 声明 v2.3.1。
- Orca：`stablyai/orca` 参考 `53fbfded41b8b0462d7ccd029475f89d12aa9bf5`。

实施时应自动读取实际 HEAD、工作树和运行环境；上列 SHA 只用于参考来源，不可强制 checkout 或回退用户代码。

## 开发边界

本包不要求重新做产品优劣比较、探索性 PoC、完整 Orca UI 移植或 Fork，不要求向 GitHub 发布/合并/Tag/生产切换。工程所需的真实协议与集成、故障注入、回归和迁移演练**必须保留**。不为新 Harness 编造成功支持，不从原生输出猜 Agent Reply。
