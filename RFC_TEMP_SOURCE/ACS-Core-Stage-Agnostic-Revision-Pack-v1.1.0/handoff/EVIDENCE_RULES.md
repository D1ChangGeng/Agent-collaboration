# 证据要求与不冒认原则

每条真实验证报告必须包含：目标源码 commit/tree/dirty patch digest、实际运行包版本、Harness/Session/Host OS、使用的权限模式、输入/返回/原始日志（对私信做安全脱敏）、命令及退出码、观察时间、失败和限制。人工声称已实施不作为验收证据。

证据类别：`package_static`、`unit`、`controlled_integration`、`native_protocol`、`independent_agent_e2e`、`orca_host_integration`。不得越级引用。原始证据可在隔离环境 `integration_evidence/...` 记录，不能把用户真实私信和凭据当夹具。

状态 `blocked` 表示实现/资格无法完成但有明确阻塞原因；与 `unsupported_verified` 及 `out_of_scope_now` 不同。若某必需 P0/P1 条件未完成，不得整体声称通过。Host 缺少公开接口不自动令 ACS Core P0 失败。
