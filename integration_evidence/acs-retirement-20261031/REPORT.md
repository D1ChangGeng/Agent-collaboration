# 默认任务运行域退出、历史采用与正式接收器验收

源码提交 `3908b1fc7bf7459dadc36b65534f3d15ee1d5bf1`，分支
`codex/core-cleanup`，基线 `75417fdd01d0cff0d0fe604d5614c3430b76fc29`。
完整目标保持 active；以下仅声明已取得证据的范围。

## 实际代码

- 删除默认任务、Review、旧 Watcher/消费模块 `project_work.py`、
  `project_inbox.py`、`project_continuation.py`。通用分页归入 `project_common.py`，
  当前资源/活动读取归入 `project_resources.py`；ProjectService 中任务控制和
  业务权限表退出。旧输入模型/投影断言只留作历史测试材料。
- `read_resource` 不再公开任务对象；活动只显示当前项目配置及真实参与者的
  通信事件。以移走 18 类旧任务表的真实数据库验证消息、上下文、资源、活动和
  订阅路径；未知消息直接报告不存在，不回落任务 JOIN。工具合同更新为 `/8`。
- `communication_archives` 是原包的派生项目索引，保存实际已有的关联、原始
  principal、收件 Slot 和原记录摘要。`communication_archive.py`、只读默认的
  `acs_communication_inventory.py` 提供盘点、预览哈希和幂等条件采用。
  关联未知不猜测，冲突不覆盖，原包/命令/回复/防重记录不改写。
- `project_archive.py` 延迟加载，只读原包与已存 Native 结果；历史读取不消费。
  作者 Slot、收件 principal 不足时返回 unknown，历史 Native 结果不能进入
  新的主动回复等待。索引采用后，历史读取也不 JOIN 工作关联表。
- 启动只读验证当前 Schema，未采用时返回 `project_schema_adoption_required`，
  不由 stdio/HTTP 启动迁移。LF/CRLF 的等价 SQL 校验仍保留，未知内容拒绝。
- 正式 Codex Receiver Factory 移除 Collector、结果投影和任务状态读取；
  不再要求 artifact_root。旧任务包在 Native 前拒绝，已有配置中的旧字段可
  保留但不创建执行链。Node 登记不再要求任务 Attempt/结果权限。
- 实测修复：共享接收器从登记的 Node 取得观察者身份，单独校验已提交的真实
  发件人；观察者/生产者登记仍逐次验证。Client-origin 续投从封存包和已登记
  Client 恢复，未登记者拒绝。旧 Authority 代际的联系人不会被当作可发起身份。
- Windows Job 的进程标签使用操作与绑定的有界摘要，原操作 ID 和映射保存在
  Journal；修复 Factory 默认生命周期 ID 含冒号而无法启动的实际故障，所属
  进程验证没有放宽。

## 已运行的验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 当前通信/归档/退出/身份/通知/HTTP/等待 | 101 passed / 2 skipped | `integration-final.xml` |
| 接收器、Driver、投递回归 | 165 passed / 6 skipped | `runtime-final.xml` |
| 工具和技能合同 | 15 passed | 实际 unittest 运行 |
| Windows 完整组件 | 209 passed / 1343 skipped | `components-windows.xml`；不是数据库/模型全通过 |
| Linux 登记/撤销/历史回归 | 33 passed | `enrollment-linux-identified.xml`，真实 PG/签名 |
| Linux 非 Systemd 完整组件 | 875 passed / 652 skipped | `components-linux-final.xml` |
| 正式 Factory 实际会话准备 | 1 passed，3.624 秒 | `factory-lifecycle.xml`、`actual-factory-session.json` |
| 正式 Factory 实际 A↔B | 1 passed，55.111 秒 | `factory-agent-loop.xml` |
| 同路径实际 Native ACK 未知 | 1 passed，107.833 秒 | `factory-ack-unknown.xml` |
| PostgreSQL 原生导出/恢复演练 | 1 passed，6.579 秒 | `backup-restore.xml`、`backup-restore-facts.json` |
| wheel 实际安装运行 | 2 条自然消息、1 条关联回复、零 Work/AcceptedState | `installed-candidate-final.json` |

实际 Native 目录在此前证据目录中：`invoke-458e6afe6dc9` 和
`invoke-661f14220608`。A/B 使用独立身份、MCP 与 Codex 上下文。正式
`CodexReceiverCapacity` 通过真实登记启动 B；A 普通发信，B 自己经正常工具
回信，WorkItem 和 Collector 均为零。ACK 未知是在真实 turn/start 返回后
注入观察丢失；重复原操作两次仍 uncertain，总 Native 次数为一。
不是接收器替身、评测器转发或 terminal 合成回复。

Native 为 Windows Codex `0.166.0-alpha.5.1`。第三方凭据沿用户明确授权仅在
隔离测试子进程使用，用户默认配置未写入。这些时长含模型与网络，不等同于
ACS 传输性能。共享模式授权有真实 PG 证据；未声称其受限 Harness 配置已在
本机完成真实模型资格测试。

## 恢复演练的实际边界

对标记为 isolated-communication-tests 的 PostgreSQL 16 容器使用
`pg_dump --snapshot`，恢复到唯一新建测试库；82 张表的行数/数据摘要完全
一致。数据包含原始旧包、自然消息、主动关联回复、未知派发与快照后发生的
模拟 Native 效果。随后隔离旧 Authority/未决状态，以新只读代际读取历史，
移走任务表后旧包仍可读，旧操作不重放。

该演练使用真实 PG/SQLite/公共工具，Agent 行为由脚本及明确 Fixture Driver
完成，没有请求模型。恢复库已按唯一名称/归属核对后删除。生产还须验证旧
进程/Node 隔离、Node Journal 和外部 artifact 文件；不能把数据库恢复当作
执行权恢复，也不能保证旧二进制一键回滚。

## Linux 环境与保留失败

源码归档和独立 Python 3.12 环境位于 WSL /tmp，未修改 Windows .venv 或
用户 Codex。首次归档缺少管理目录和 Git 身份，补齐实际跟踪文件并建立独立
测试 Git 身份后，五个夹具通过。一个时钟夹具补齐新发送方参数，断言保留。
`components-linux-current.xml` 为 870 passed / 5 failed / 652 skipped；五项
仅因夹具源目录无 Git，`components-linux-git-fixture.xml` 全部通过。

完整 Linux 运行还保留 17 项 Systemd 失败：本机 systemctl 不返回受限配置
要求的全部身份/策略属性，未放宽保护，也未计通过。相关源码与原 HEAD 未变。
本轮后续 Linux 非 Systemd 完整运行 875 passed / 652 skipped，未声称本机受限 Systemd 可部署。
已只读核对，无本轮残留活动 Systemd 服务。

`actual-factory-session.xml`、`factory-native.xml`、`receiver-retirement.xml`、
`archive-contract.xml` 等失败保留：分别定位旧登记权限、Windows 标签、只读
Inbox 的测试选择及历史等待入口；均经源码或适用夹具纠正再验证。没有为了
全绿恢复已撤回的任务接口。原始 trace 和回放日志保留。

## 交付和仍待完成

源码和安装候选均可本地审阅；用户原有 README 字节与其他未提交资料保留。
无 Push、生产清理、正式发布或远端服务切换。Native 哈希记录保留原运行源码；
随后仅清理 EOF 空白的文件有独立 AST 等价记录，未改写原验收材料。

下一步继续最终需求逐项核实、默认 Domain/存储与 Native 记录的剩余边界，
以及实际声明范围的接收采用、跨机器/Codex↔OpenCode、等待重启窗口和资源
测量。旧 Domain 历史库和混合表尚未物理清理，生产存量/外部文件未审计；
不把本阶段等同于全部 WP00–WP06 或正式 Gate 完成。
