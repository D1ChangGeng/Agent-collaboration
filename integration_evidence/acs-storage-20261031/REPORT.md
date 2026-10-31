# 最小新装存储、显式采用与真实 MCP 通道

分支 `codex/core-cleanup`，接续 `f0e9b9fc7bb9f85d1e2a05a0fc442c83280c219a`。
完整目标仍 active。本阶段只在隔离数据库、临时 Native home 和远端 /tmp 中
验证，未部署、Push、切换现有服务或清理生产数据。

## 实际代码

- R02/R30：`communication_core_schema.sql` 只创建身份、授权、消息传输、
  回执、防重、Node/Runtime 与技术事件表；`project_schema.sql` 只保留当前
  Project/Route/联系人/SourceBinding/通知 Session。新装从 82 表减为 46 表，
  36 张旧 Work/Review/Lease/Effect/业务 Evidence/Collector/Watcher 表不再创建。
  Core Inbox 镜像、Outbox、delivery_attempts、回执及关键唯一索引继续承担
  一致性核对和防重。原始旧 DDL/迁移助手移到历史测试夹具，不进入 wheel。
- R31：新增 `communication_storage.py`，独立记录 `acs-communication-core/1`。
  已知完整 1.13 的精确 LF/CRLF 指纹可以显式采用，旧 metadata 和所有原始行
  保留；Project 已知 schema 1 明确采用到 2。未知版本、未知 checksum、
  无版本存量、缺失权威账本或关键唯一防重索引均拒绝，不静默建空账本代替恢复。
- R31/R32：正常 stdio/HTTP 启动只读校验全部当前关系与 Core 防重索引。
  `acs_communication_adopt.py` 默认 READ ONLY，预览 Schema、metadata、表和
  目标 SQL 哈希；只有绑定预览哈希的显式 --apply 执行单事务采用。
  不创建身份、不发起 Native、不删除数据，历史关联索引仍由单独工具处理。
  自动更新边界把新 SQL/采用代码识别为需审阅的契约变化。
- R27/R32：真实模型暴露 ACS 与原生 send_message 的工具同名歧义。
  `native_delivery.py` 的 `acs-native-context/1` 明示 Project、ACS MCP 通道、
  真实发送者和准确关联句柄，提供不含代写正文的 reply_action/read_action。
  正文保持原样。MCP 初始化指引也明确 ACS 联系人与原生 agent path 的区别，
  保留原生工具集；没有靠禁用原生消息工具让验收通过。

## 验证

| 范围 | 实际结果 | 证据 |
|---|---|---|
| 新装/采用/拒绝/技术入口及通信回归 | 81 passed / 2 skipped | `final.xml`；前两轮结果也保留 |
| 历史数据与旧迁移夹具 | 63 passed / 75 skipped | `historical.xml`；不代表恢复旧产品功能或 Linux 资格 |
| 安装与更新边界 | 27 passed | `installer-final.xml`；受控系统/网络替身 |
| 实际 stdio 握手及 ACS 指引读回 | 1 passed | `mcp-instructions.xml` |
| 新装 46 表，正式 Factory 实际 A↔B | 1 passed，76.79 秒 | `native-factory.xml`、`native/final/` |
| 最终源码，实际 Native ACK 观察丢失 | 1 passed，74.99 秒 | `native-ack-unknown.xml`、`native/ack-unknown/` |
| 最终源码，Windows Codex ↔ 1302-1 OpenCode | 1 passed，162.96 秒 | `cross-harness.xml`、`cross/final/`；message_only |
| 真实 pg_dump/pg_restore 混合存量恢复 | 1 passed，6.18 秒，82 张表一致 | `backup-restore.xml`、`backup/*/backup-restore-facts.json` |
| wheel 实际安装与公开工具 | 46 表、2 条消息、1 条关联回复 | `installed-candidate.json`；脚本 Agent，无模型 |

新装验收查明 Work 表本身不存在，而不只是行数为零。普通 A/B 是不同身份、
不同模型上下文，各自调用正常 ACS 工具；评测器未转发正文、提供答案、补造
reply_to 或将终态输出投影为回信。Windows Codex 为 0.166.0-alpha.5.1，
远端 OpenCode 为 1.18.34。模型/网络耗时不是 ACS 传输延迟。

正式 Factory 产生一次 Native turn/start、2 条自然消息和1条主动关联回复，
Collector=false。B 的原始 rollout 证明它经 Harness exec 工具自行发现并调用
`tools.mcp__acs__send_message`，不是调用原生 agent-path send_message。
ACK 未知是在真实 turn/start 返回后注入观察丢失；随后两个同操作重试均为
uncertain，Native 次数仍为一，B 的实际回信仍可被 A 准确取得。

跨机方向通过回环 SSH 数据库转发访问共享隔离 Authority，双方通过各自 MCP
收发。这证明该 message_only 方向，不是跨机签名 Receiver / OpenCode Native
自动激活验收。远端正式 checkout、默认 Provider、全局技能与 Desktop 配置
均未更换；获准第三方凭据只用于测试子进程，不写入命令或输出。

最终 wheel SHA256：`2d7d54a0ec4462192e26a110d384896ff9e54051b0e16e23c2ee37b274c5af62`。
104 个安装的 Runtime/Deployment Python/SQL 文件逐字节匹配最终源码，旧 DDL
和测试夹具未打包。版本 0.1.0 是已有组件版本，与开发包 v2.33 无映射。
前两个候选与各自安装事实另存，没有改写旧阶段证据。

## 保留失败与实际边界

- `storage-first.xml`：最初把显式采用新增的派生归档索引也当作禁止变化。
  测试改为逐行保留所有原始数据，只允许已核实关联新增索引，并保持未知
  版本/缺账本/缺防重索引的拒绝断言。
- `backup-fixture-default-failure.xml`：历史写入夹具依赖旧事件 target_kind
  默认值。夹具现显式记录旧 work_item 类型；正式新装 Schema 和守卫保持严格。
- `installer-sandbox-failure.xml`：Windows sandbox 临时目录权限导致启动/清理
  失败。改用本工作树的独立临时目录后原断言全部通过，没有改安装行为取巧。
- `native-channel-ambiguity.xml`、`native/channel-ambiguity/`：MCP 已 ready，
  B 错用原生消息工具，A 等待未被错误解除。改进 Native 上下文后真实闭环通过。
  `cross-sender-channel.xml`、`cross/sender-channel/` 保留发送端同类误选；
  加强初始化指引后，在保持原始任务提示不变的情况下完成真实跨机交换。
- `mcp-instruction-edit-failure.xml` / `cross-mcp-edit-failure.xml` 记录一次编辑
  引入的重复 instructions 参数；编译与真实握手捕获并修复，后续验收使用修复源码。

备份演练使用真实 PostgreSQL 与受控 Native 效果，没有模型；它验证包含历史
记录的混合库，不能替代生产切换、Node journal/外部 artifact 一致性或旧进程
隔离验收。恢复库已按唯一归属清理。生产旧表仍保留，没有承诺旧二进制一键回滚。

尚需继续：剩余跨机 Native/OpenCode receiver、真实等待进程重启窗口、受限
Harness 资格及最终需求审查。部分未绑定历史模块仍在源码中，需要继续清理。
不把本阶段表数下降、组件绿色或单一平台模型闭环称为全部 WP 或正式 Gate 完成。
