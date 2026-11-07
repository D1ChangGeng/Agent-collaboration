# 证据目录约定

建议实际实现输出 `integration_evidence/acs-harness-communication-<date>/`。保留 baseline.json、commands.jsonl、result.json、raw/、failure-history.md、source-manifest.json 和 checksums。

每条 evidence record：id、evidence_class、source_revision、environment_ref、command、exit_code、observed_at、artifacts[{path,sha256}]、claims、limitations。证据类别不能由描述文字自动提升。脚本 Agent 不等于独立模型；fake Provider 不等于实际 Native；编译/类型通过不等于已接入 Orca。

`tools/validate_trace.py` 只检查提供的轨迹结构与部分不变量，不证明这些轨迹真实发生、不证明对外安全，也不能代替真实集成测试。
