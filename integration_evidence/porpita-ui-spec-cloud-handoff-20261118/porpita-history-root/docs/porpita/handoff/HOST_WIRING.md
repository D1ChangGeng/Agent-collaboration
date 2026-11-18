# 实际宿主接线记录

当前是 Windows x64 开发构建，产品整体验收仍在进行。源码未提交，尚无安装版验收。

## 已接通的真实路径

- ACS SDK：`src/shared/acs/`，按 `SOURCE.json` 记录采用 e5d71968 的 SDK；仅调整导入扩展名。
  Core wheel 采用同一基线及 dependency manifest 中明确列出的两个本地 Runtime 增量。
- 服务组合：`resources/porpita-core/porpita_core.py`，真实 PostgreSQL、DomainAuthority、ProjectService、
  通信 HTTP/MCP 与维护循环。`porpita_identities.py` 使用实际 configure_root/configure_team caller binding。
- 接收：`porpita_receivers.py` 组合既有 `ExistingOrcaReceiverBackend`、`OrcaReceiverRouter`、
  `ReceiverHTTPServer`；`porpita_receiver_enrollment.py` 使用既有 Node challenge、Runtime、TLS Endpoint
  与 transport key 登记。没有另起 Native Driver。
- Host owner：`src/main/porpita/native-host-ownership.ts` 从实际 Host conversation、当前 child 对象、
  fence 和 generation 读取；WeakMap token 随 child 对象替换。模型名称或 CLI 参数不能声明 owner。
- 进程边界：Python Core→已登记 TLS Receiver→受独立 Host key 保护的 Node loopback bridge→实际 Host。
  Host→Core 原 operation 验证在同一个已认证私有连接上执行，返回原始已验证 DTO。
- Native 获取：`native-host-extension.ts` 调用原 Host at-rest open 与
  `startStructuredAgentSessionAgentForOperation`，不另建会话。恢复路径为所有保存的可见 Native tab
  重新登记接收容量，后台 tab 不依赖正在显示。
- 原生输入：`native-receiver-input.ts` 从目标 Actor 的真实 SDK 读取消息，使用原 `sendPlan` 和 fingerprint，
  调用 Host 原输入队列。`native-operation-id.ts` 从原已验签 admission 的 issued_at 与 operation id
  生成符合 Host 既有格式的稳定 id。
- 原子边界：`structured-agent-session-input-handover.ts` 的 serialize→validate→prepare→validate→enqueue
  内再次核验原 Core 操作与当前 child；验证后重新检查 Host readiness，随后同步 enqueue。
- 回执：只有原 Native journal 的 accepted submission 才形成正 Native ACK；journal ok/pending 不算。
  `reconcileNativeInput` 只回查同一 operation 的原 input，不启动、重发或选择其他会话。
- Agent MCP：Codex 的独立 app-server spawn 使用 per-session URL 和凭据环境；ACP 的 new/resume
  使用真实 mcpServers 参数。Actor key 加密保存在 Porpita 私有目录，模型不取得 Human key。
  Codex 只禁用其实际 TOML 中已有的旧 ACS server，避免创建没有 transport 的空表。

## 实测

`../evidence/20261108/real-native-live03.json` 记录真实 Codex→OpenCode Native 接收→明确 reply_to→Codex
精确等待闭环。原请求达到 runtime_acknowledged，回信达到 target_inbox_committed，两个原生界面截图
保留在同一目录。失败的先前请求仍在各自的 budget_exhausted/uncertain 状态，未以重发掩盖。

## 尚待接通和验收

全部 14 条旧通信路径的退出、workflow receipt 与 ACS handle 关联、Native 附件材料化、完整 Native
SourceReader/SourceLink、远端服务与接收恢复、busy/权限/故障矩阵、安装版同构建闭环。
普通 Native 用户输入、工具、审批、编辑器、终端与输出继续由继承的 Host 实现负责。
