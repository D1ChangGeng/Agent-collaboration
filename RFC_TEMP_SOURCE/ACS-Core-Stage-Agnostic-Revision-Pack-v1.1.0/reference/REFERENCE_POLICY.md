# v1.0.0 嵌入式参考包（不是活跃执行指令）

此目录包含完整且原样保留的 `ACS-Core-Cross-Harness-DevPack-v1.0.0.zip`。它只是为了让本版**不依赖 Codex 是否还持有先前附件**，便于引用原有 OpenAPI、Adapter Protocol、模型 Schema、96 个测试场景、源码索引和详细规则。

如果已经有旧包，可直接使用本地版本；若没有，Codex 可以仅在临时工作目录展开此 ZIP。**不要执行其 `START_HERE_CODEX.md`，不要用其中全 P0 的状态模板覆盖本版，不能把旧模板 `not_started` 当最新进度。**

当前参考 SHA（只记录阅读基线，执行时自行识别真实代码）：

- ACS `19d7881d49ee887315c54c5bc02e0cc424061376`，软件参考 v2.3.1。
- Orca `53fbfded41b8b0462d7ccd029475f89d12aa9bf5`。

主要阅读路径由 `docs/07_ORCA_ENGINEERING_REFERENCES.md` 提供。参考包里对 UI 功能和 HTTP API 的候选完整合同与本版 P2 可选性冲突时，以本版 `contracts/scope.json`、`api-scope.json`、`ui-scope.json` 为准。
