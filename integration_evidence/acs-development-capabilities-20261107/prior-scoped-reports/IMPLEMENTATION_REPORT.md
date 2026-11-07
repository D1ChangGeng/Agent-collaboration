# ACS Core v1.1.0 开发与验收结果

截至 2026-11-07，P1 通信服务与 P2 扩展完成本地验收。P0 为
`qualified_with_specific_blockers`：已验证的 Codex/OpenCode owner/native 组合成立，
其他平台、权限模式和实际 Orca Host 按下述矩阵单列。此结论不代表全平台原生资格。

## 0. 实际版本和交付源码

- 源码：`D:\Chatgpt\Agent-collaboration`，分支 `codex/core-cleanup`。
- HEAD：`19d7881d49ee887315c54c5bc02e0cc424061376`；HEAD tree：`8856b23e59d50eccb1198475e84937c48a71b0bb`。
- 工作树含原有成果及本轮增量，尚未提交、Push、合并、发布或生产切换。
- 当前候选包元数据版本 2.3.1；wheel SHA-256：`9678bdb5e4b70de1f468247cd1d4607ffe46172c0cc2dce8c2caafc961fb94b9`。
  186 个包内文件与当前源码、临时安装后的字节一致，见 `package-facts.json`。
- 跟踪改动的原始 binary diff 摘要、每轮命令、逐文件源码摘要与原始结果分别见
  `source-state.json` 和各测试 JSON/XML/log；HEAD 本身不代表这批未提交源码。

## 1. 范围、实现和实际增量

25 项 C、40 项 R、96 个原始场景、35 个 API 和 30 项客户端来源已逐项映射，
见 `acceptance-audit.json`、`requirements-assessment.json`、`api-assessment.json`、
`ui-contract-assessment.json`。开发包原件和此前失败记录均保留。

本次修复普通 HTTP 消息读取对旧 facade 的兼容问题：默认和显式 false 不传新增
`include_native_source` 参数，显式 true 才请求来源扩展；原文和独立续读保持原语义。
`source-impact-review.json` 验证反向差异能精确重建修复前捕获字节，差异见 `runtime-change.diff`。
三条路径均有直接回归。另在既有 Runtime/SDK 实现上补齐 9 项直接验收：双设备读水位和请求去重、
真实 OAuth/TCP 的 13 个 P2 操作、双连接草稿 CAS、四个真实写进程中断点、
安装后后台维护，以及附件 URL/私有 ID 的实际拒绝。初轮夹具问题和复测分开记录。
现有消息、operation、Outbox、Node/DriverJournal 和 Root/Route 身份继续作为原权威。

## 2. P0：受信通信与 Native 边界

C01–C11 在声明配置内的实现与安全回归已核验。可信 sender、显式 reply_to、
message_only、非消费 read、长 UTF-8 续读、断连后原 handle 恢复、签名生命周期、
最后准入、人工 blocker、旧代次隔离和未知副作用不重投均有对应证据。

- 保留的 E4（Native/Core-MCP 栈字节一致，HTTP 增量单列）：Windows Codex 0.166.0 → WSL OpenCode 1.18.34，
  普通 A/B、两条消息、一条显式关联回复、B 一次 Native 输入、A 的真实 wait satisfied。
  Native/签名接收器及 Project/MCP 收发/等待机制保持原字节。901 个捕获文件中的
  普通 HTTP facade 与对应测试有已审查增量，已由当前组合回归重验，见 `retained-native-evidence.json`。
- Codex 接收工厂的独立 B 输入/显式回复证据 b，以及两端签名生命周期 E3，按
  相同 Native 栈摘要保留。b 的旧 Core wait 不冒充最终 wait；后者由独立 e 和当前 PG 验证。
- 当前 wheel 的独立后台进程在发送客户端退出后推进已提交消息；这是隔离安装 E2，
  Native 使用明确的回调夹具，不代表生产服务升级或真实模型轮次。

原始场景并未被一律改写为 pass：T006 依据 v1.1 的旧 MCP 兼容优先级保留
提交前 `endpoint_binding_ambiguous` 拒绝，零广播，随后可显式选择接收端；它不等于
旧“先落 Inbox”的原样通过。T031 的安全原生 enqueue 前提未在当前支持集中成立，
按 typed unsupported/busy deferred 验证。其余场景也保留原 GWT 与实际证据范围。

`CORE_P0_QUALIFIED = qualified_with_specific_blockers`。

## 3. P1：可由客户端实际消费的通信服务

22 个 P1 操作由实际 Node SDK → OAuth/TCP/HTTP/SSE → PG 链路验证，
包括身份/项目/联系人、空会话到首条消息、发送/原文/显式回复、投递/原 operation、
receiver/恢复/notice、快照、断线重放和撤权。MCP 与 HTTP 使用同一 Domain/权限。

26 个 P1 场景与 30 项来源合同逐项核对；NativeLink/SourceLink 保留独立来源和
Host 授权，Native 输出不能成为 ACS reply。Orca 端口通过协议、单 owner、
授权和 typed unavailable 测试；本地没有实际接通可资格化的 Orca Host。

`CLIENT_P1_CONTRACT_READY = true`；`ORCA_HOST_QUALIFIED = false`。

## 4. P2：本次明确交付的扩展

| 变更项 | 当前行为与验证 |
|---|---|
| C22 | viewer 私有读水位/未读及 notice seen；跨设备可读，水位不回退，不改变 Native/reply |
| C23 | viewer 私有草稿、静音/归档偏好；双设备 CAS 一方 409，精确重试保存原结果 |
| C24 | 私有 reservation、完整上传、digest/MIME/大小校验、finalize、受权读取、消息 pin 与清理；断线重传复用原计划；URL 抓取字段与猜测私有 ID 被拒绝 |
| C25 | 受权消息全文的字面子串搜索、UTF-8 摘要、稳定游标与撤权；不泄漏其他参与者正文或数量 |

13 个 P2 API 都有真实服务调用证据。附件仍由明确配置启用；Native 二进制
附件注入继续 typed unsupported。个人状态和草稿不会扩大收发信或项目权限。
`P2_EXTENSIONS_READY = true`，限定已列服务行为。

## 5. 验证、失败和复现

| 批次 | 通过 | 失败/错误 | 跳过 | 原始证据 |
|---|---:|---:|---:|---|
| p2-initial | 343 | 0 | 0 | `p2-initial.xml` |
| exact-completion-b | 8 | 0 | 0 | `exact-completion-b.xml` |
| core-components-final | 1094 | 0 | 24 | `core-components-final.xml` |
| native-fences-components-final | 191 | 0 | 7 | `native-fences-components-final.xml` |
| read-compatibility-final | 3 | 0 | 0 | `read-compatibility-final.xml` |
| p0-p1-final | 519 | 0 | 3 | `p0-p1-final.xml` |
| SDK/严格 TypeScript | 210 | 0 | 0 | `sdk-verification.json`、`sdk.log`、`typescript.log` |

各行是独立批次，存在重叠，不能相加为单次全量通过。每轮捕获字节在运行前后
不变；最终组合与当前一致，历史组件/存储批次的 HTTP-only 增量由最终组合覆盖，
逐文件差异记录在 audit 中。跳过项按真实模型 opt-in、缺额外运行环境或平台条件逐条保存在 XML/log；
当前已有独立 E3/E4 证据与它们分别记录。

E0 开发包 50 文件及 manifest 校验、scope 一致性、客户端/SDK/P1 OpenAPI
导出检查、Ruff 与严格 TypeScript 通过。当前 wheel 离线构建并临时安装，未改变既有安装。
常用复现入口为 `tools/runtime/cross_harness_verify.py`，仅使用命名的
`acs-communication-test-20261031 / acs_communication_test`；精确命令见每轮 JSON。
本轮没有调用外部模型服务，也没有重放历史 Native 验收计划；本地通信 API 均已实际调用验证。

首轮组合为 500 通过、1 失败、3 跳过，暴露并修复了上述旧读取调用形状兼容问题；
原断言完整保留，最终组合对修复后的当前源码重新验收。首次收集缺 YAML 工具、
沙箱内无进展后中断、三项新增夹具错误及目标路径错误
都保留在各自旧结果中；最终通过结果不覆盖它们。早期证据的状态改写前另存于
`prior-assessments/`，当前 canonical 状态仍在原 `acs-stage-agnostic-20261106/adoption-state.json`。

## 6. 数据迁移与回滚

本次增量没有生产 schema 或用户数据变更。现有显式 additive adoption、
旧作者未知保留、DriverJournal adoption/失败回滚、旧消息/回复/请求键/未知输入保留
均由真实 PG/SQLite 用例核验。四个事务中断点在真实写进程被停止后，消息、回复、
operation、Outbox、dedup 和事件 intent 全部回滚；同原 key 恢复只得到一个逻辑结果。
安装验收验证只读启动检查，正常启动不隐式采用旧 schema。

## 7. 尚未取得的资格及具体前提

完整记录见 `qualification-matrix.json`。实际 Orca Host 需要其受信 verifier adapter
及串行原子输入扩展被注册并独立运行；远端原始 journal reader 也需明确的受权读端口。
物理双机和 Windows Shared/restricted Native 组合需要对应隔离环境与实际版本/权限验收。
当前原进程失效时的自动 cold recovery 没有受信的原 process/session/generation 证明，
继续 unknown/unsupported；单独空 Session CLI 探测不扩大生产恢复能力。

这些组合没有被冒认为已通过。WSL 清理仅证明自有进程组已空，
`subtree_containment=false`。新增 Claude/Pi 完整 Driver 没有本包 25 项所需的确切目标资格。
本地声明范围内的实现与验收已闭合；受控 Native/Host 夹具仅用于明确的协议测试，
实机范围按矩阵限定。

## 8. 交付状态

实际源码与证据保留在当前工程工作树，未提交、未 Push、未部署。没有其他 clone
的同步动作。扩大支持组合时应先具备第 7 节条件，再取得独立资格；当前本地交付
由本报告、机器状态与原始证据共同限定。
