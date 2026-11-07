# 01｜阶段无关接续：先读当前事实，再最小增量开发

## 五种实际输入状态，同一工作方法

| 当前真实状态 | Codex 行为 | 禁止 |
|---|---|---|
| 旧包完全未开始 | 以本版 P0→P1 主线从现有源码实施 | 按旧全量必交清单强行扩展 P2 |
| 旧包已部分实现 | 核验已完成部分，对缺口做兼容增量 | 重新生成第二套 Domain/Outbox/Adapter |
| 旧包已完成 P0，P1 开发中 | P0 回归，优先续完 P1 必需通信接口 | 因老工作包顺序重新开发 P0 |
| 旧包已完成 P0/P1 或更多 | 实际运行资格/边界自检，处理不符合本版要求的差异 | 为“有改动可交”制造无意义提交 |
| 旧包 P2 已进行/完成 | 保留已工作成果、测试与迁移；安全修复照常 | 为本版“降级 P2”删除用户成果 |

本表是概念演示；**Codex 不需要事先选一个阶段**。每项 change item 可以有独立状态，整体项目可能同时符合多行。

## 自适应操作规则（不可省）

1. 真实仓库是唯一实现事实。读取 `git status --porcelain=v1`、`rev-parse HEAD`、项目自身说明、已有代码/SQL/测试、安装与连接事实。可用 `tools/capture_state.py` 快速生成**只读索引**，但文件存在不能自动认定完成。
2. 读取旧包原始开发包（若可得）、历史 Work 包结果以及证据索引。把旧包标为 `prior_intent`，旧状态字段视为 `claim_to_verify`。记录新的 scope 修订覆盖旧要求的位置。
3. 逐个检查 `contracts/change-items.json`：已有代码、运行时证据、测试正反例、授权边界、Host 版本。给每项状态：`retained_verified`、`implemented_needs_evidence`、`partial`、`absent`、`incompatible`、`blocked`、`out_of_scope_now`。`retained_verified` 必须有证据 ID。
4. 根据未完成的 P0/P1 条目组装**动态依赖图**，只做尚有缺口的步骤；不存在某一全局“重新从 WP00 开始”的要求。
5. 每个 P0 增量优先从现有实现寻找扩展点。没有 ABI/迁移需要时，不强迫添加 Adapter 第二套类层。每个 P1 API 复用已存在 Domain/查询和安全边界。
6. 维护小型 `adoption-state.json` 与 `SCOPE-DELTA-REPORT.md`，持续更新，不要求用户解释旧进度。该文件属于开发证据，**不直接写回现有生产存储或覆盖旧日志**。
7. 碰到真实外部权限/凭据/机器缺口则对应标 blocked，继续其他可做工作；未经授权的生产 Native、合并和发布一律不执行。

## 版本、迁移和工作树

- ACS 软件版本、Git HEAD、当前工作树、已安装服务和开发包版本分别记录。不要依赖固定 v2.3.1，也不要要求回滚到旧提交。
- 发现旧版已添加新的表或 endpoint，先读实际 schema 和数据后再实施；迁移应 additive、可显式 adopt/恢复。维护旧客户端兼容和身份历史。
- 未提交修改可能是 Codex 正在进行的工作：按文件级别保留、审查其目的，不运行 `git reset --hard`、无审批的 `clean` 或强制回滚。
- 既有 P2 已正确实现就保留；仅将其从新的完成 gate 移除。若 P2 正在开发且依赖 P0 基础正确性，则允许完成保证完整性的最小修复。

## 执行优先级不是任务编号

以 P0 正确性回归、P0 发现的真实缺口、P1 基础 facade/订阅/宿主 port 的依赖图为序。机器清单里的旧 `WP07` 包含附件和 NativeLink 两种性质：必须拆开判断，不可因为包内出现一项 P2 就阻塞另一项 P1。

## 不确定与例外

源码未核实 → `unknown`；类型/fixture 通过但未接真实服务 → `implemented_needs_evidence`；只有宿主契约无公开 Host action → `host_extension_required`，不能写为 `Orca-qualified`。失败用真实原始日志与 source revision 记录。自适应不等于绕开验收。
