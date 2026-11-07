# ACS Core｜v1.1.0 实施结果（由 Codex 在实际开发后填写）

**禁止预填成功。** 以下所有 `UNASSESSSED` 在有具体运行证据后才能改变。不得把此文件的模板当作已经完成的工程结果。

## 0. 版本与实际代码

- ACS source HEAD/tree/dirty patch digest：UNASSESSED
- 实际安装/运行版本和主机、授权范围：UNASSESSED
- Orca 参考/实际 Host 版本（如有）：UNASSESSED
- 旧 v1.0.0 在接收本修订包时的实际完成状态：由源码/证据核对，不要求用户提供

## 1. 范围变化与成果保留

表：`原旧条款/工作包 → 新 P0/P1/P2 → 当前代码与迁移 → 所采取动作 → 原有成果是否保留 → 证据 ID`。

## 2. P0：独立 ACS Core（是否通过）

- 旧可信身份/回复、message_only、wait、read、历史/权限：
- Adapter describe/observe/admit/reconcile：
- 原生最后准入/队列/审批/草稿：
- Native unknown 防重/绑定代次/恢复：
- Codex/OpenCode 真正 Native 资格，具体版本/OS/Host/授权：
- 多主机/维护器/故障通知及正确性：
- 实际自动化测试和原始证据：
- `CORE_P0_QUALIFIED`: true / false / qualified_with_specific_blockers（列出不满足的支持组合）

## 3. P1：ACS 通信客户端服务（是否通过）

- 实际 22 个必需 operationId 通过状态（不是仅 OpenAPI 存在）：
- snapshot→subscribe 竞态/撤销/replay/headless：
- Conversation/Message/provenance/NativeLink：
- Orca Host Port/单一 input owner/typed `host_extension_required`：
- UI01–UI30 按 scope/authority/delegate 的覆盖与边界：
- `CLIENT_P1_CONTRACT_READY`: true / false / qualified_with_specific_blockers
- `ORCA_HOST_QUALIFIED`: true / false / not_tested / host_extension_required

## 4. P2：已存在/未实施（不阻塞）

逐项记录：read/unread、draft、preferences、search、binary attachments、notification seen。已实现者列安全/兼容回归；未实现标 optional/deferred。不得把 P2 缺失计入 P0/P1 失败。

## 5. 测试与失败

按 E0–E5 记录命令、exit code、源码版本、机器/账号、evidence_class、原始日志路径/hash、初次失败及复测。受控 double 不算真实 Native 资格；真实模型若未独立发信/回复则不算 E4。

## 6. 数据迁移与回滚

记录实际 schema delta、旧 Client/read/write 兼容、数据/历史保留、备份恢复演练、已发生 Native 副作用调和及混合版本能力拒绝。没有生产授权时明确仅隔离演练。

## 7. 无法验证和外部阻塞

缺少 Native 二进制/授权凭据/真实 Orca Host 端口、未实际运行的组合、仍是 unknown 的投递 outcome、权限等待/Host gap。不得变相标成成功。

## 8. 交付与下一步（无部署承诺）

代码提交/工作树清单、兼容接口目录、安装/本地运行方法、后续 P2 候选和需要明确授权的操作。默认没有 merge/tag/release/生产切换。
