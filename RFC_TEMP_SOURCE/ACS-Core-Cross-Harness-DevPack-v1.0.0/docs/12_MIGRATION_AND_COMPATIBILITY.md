# 12｜兼容、迁移和回滚

## 版本轴

保持区分软件版本、MCP catalog、message packet、client HTTP、event envelope、Adapter protocol、schema migration 和 runtime capability。现有 `acs-message/1` 原包不能仅为 UI 改版而重写。新面使用 acs-client/1、acs-event/1、acs-adapter/1；实际 catalog version 根据执行时真实值递增，不硬编码把 12 当永远当前。

## additive 数据演进

先识别现有 operations/Inbox/Outbox/journal 可承载字段，再增列/索引/新表。建议逻辑表：receiver capability observations；Native operation receipts（尽量扩展现有 delivery operations）；client conversation projection；personal read/draft/preferences；authorized event journal；attachment staging/content metadata；native links。表名是建议，不要求重复建立现有语义表。

新客户端投影允许后填：通过现有提交顺序增量扫描，原作者缺失的历史保持 unknown/archived，不猜 identity，不把旧 Native result 生成为回复。回填可中断和继续，有 checkpoint 和摘要校验。旧索引与兼容 read 在稳定切换前保留。

## 迁移流程

preflight 读实际 schema/version/checksum、表规模、活跃维护进程、磁盘与备份；仅授权的 operator 命令进行 schema adoption。先备份/恢复验证，再应用增量。新增 constraints 先清查不合规历史，不自动删除。大索引按实际数据库支持采用安全策略，避免长时间阻塞 message commit。

滚动升级先让 reader 兼容新字段，再启用新 writer/事件能力。旧 Node 不识别新字段不能收到含其不支持副作用的命令，返回 capability unsupported。旧客户端仍可发纯文本/看历史/wait；新客户端通过 meta 探测扩展。

## 回滚

应用回滚优先停止新功能写入、保留 additive 表及原操作证据，切回兼容 reader；禁止 downgrade 时删除未决 operation、幂等键或消息。Native handoff 已发生不可“数据库恢复后重新发”。若回滚需要恢复数据库，必须停下 Native admission、保存外部副作用 journal 并调和后再启用，否则可能重复执行。

旧版本不认识新 schema 时明确拒绝启动，不静默降级写入。版本化安装/active pointer/清单校验和既有 bootstrap 体系保留；升级报告记录真实主机/账号/配置/版本，不默认切换生产。

## 回归矩阵

旧 MCP → 新 Core、旧 HTTP/stdio → 新 Core、新 HTTP → 无扩展旧 receiver、新 Core → 原 Codex/OpenCode 资格环境、混合 receiver capabilities、同 principal 多 Slot、Client null Slot、Root/Route 权限变化、message_only+sync、大正文双续读、晚到回复、未知 ACK、重复 key、历史 archive、系统 notice 均必须测试。

没有版本兼容信息的“支持 latest”不可验收。支持矩阵记录精确版本和实际功能；设计支持其他 Harness 不得填为已资格化。
