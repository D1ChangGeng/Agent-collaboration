# ACS Core 跨 Harness 可靠通信增强｜Codex 开发包

**交付版本：1.0.0 · 2026-11-06 · 状态：开发规范完成，产品实现尚未执行。**

本包直接用于 ACS 现有源码的增量开发。它不是研究提案，不包含新一轮产品对比、探索性 PoC 或 UI 设计任务，也不声称已经增强或发布 ACS。

## 执行入口

把本目录与 ACS 源码放在 Codex 可读取的位置，向 Codex 提交 `START_HERE_CODEX.md` 全文。先读执行入口，再读 `docs/00_SCOPE_AND_DOD.md`、`docs/01_BASELINE_AND_EVOLUTION.md`，按 `docs/13_WORK_PACKAGES.md` 连续实施 WP00–WP10。Orca 只读参考；允许必要的无 UI 集成适配代码，不修改或发布上游仓库。

## 已固定的方向

ACS 继续作为可信通信事实的权威：稳定 Client/AgentSlot、Project/Root/Route、自然消息、显式 reply_to、权限与持久历史。Harness 差异由 Adapter 和运行时处理。Run、Task、Dispatch、Gate 不成为通信前置条件。保留 `invoke+async` 默认行为、`message_only` 不唤醒、等待超时不撤回、Native 输出不等于回复。

目标不仅是“可发送消息”，还包括完整客户端后端就绪：联系人与通信会话、历史/关系/检索、未读/通知、附件、实时同步、诊断恢复、接收端能力状态、原生会话关联，以及与 Orca 原生 Chat/工具/Diff/审批/模型设置的明确非侵入式边界。完整 UI 接入就绪不等于本轮开发 UI。

## 内容导航

| 目录 | 用途 |
|---|---|
| `docs/` | 范围、架构、正确性、Adapter、恢复、安全、HTTP/实时/Orca 集成、迁移、工作包和验收 |
| `contracts/` | OpenAPI 3.1、JSON Schema、事件/能力/错误/状态转换注册表、Python Adapter Protocol、TypeScript 集成接口 |
| `fixtures/` | 合法/非法报文与事件轨迹；仅为合成契约夹具，不是真实运行证据 |
| `tests/` | 包自身测试与目标系统验收场景；明确区分包校验和 ACS 实现验收 |
| `tools/` | 本地包校验、证据轨迹检查、源码版本记录工具 |
| `sources/` | 固定提交的来源清单、已读范围、工程吸收映射和待核对项 |
| `handoff/` | 实现状态、阶段证据、UI 就绪、迁移和最终交付模板 |
| `quality/` | 本次包校验报告；不代表 ACS 功能已实现 |

## 本地检查

```sh
python tools/validate_pack.py
python -m unittest discover -s tests -p 'test_*.py' -v
```

Python 3.12+；校验依赖在 `requirements-validation.txt`。本包不提供 ACS 服务的替代实现。契约夹具检查通过只说明规范及样例一致，不能替代真实数据库、独立入口、已安装 Harness、断线/撤销/跨机集成测试。

## 参考基线

ACS：`D1ChangGeng/Agent-collaboration@19d7881d49ee887315c54c5bc02e0cc424061376`，读取到包版本 2.3.1。
Orca：`stablyai/orca@53fbfded41b8b0462d7ccd029475f89d12aa9bf5`。

这是本包引用的观察快照，不宣称是执行时最新版本。执行时记录实际工作树和差异，保留用户未提交修改，不自动回退源码。历史开发包版本 v2.33、ACS 软件版本和本包版本彼此独立。

## 交付清单校验

`PACKAGE-MANIFEST.json` 列出交付文件、字节数与 SHA-256；`SHA256SUMS.txt` 还覆盖清单自身（不覆盖校验文件自身）。解压后使用 `python tools/verify_checksums.py` 检查完整性。校验工具只读文件。
