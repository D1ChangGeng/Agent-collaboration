# ACS P0 / P1 / P2 开发完成报告

源码提交交付见 [PUBLICATION.md](PUBLICATION.md)。下述测试源码基线和未提交状态为验收时的历史快照。

本轮按用户要求完成全部开发能力，验证覆盖单独记录。逐项审计结果为：
**25 个改造项、40 条需求、35 个 API、30 项 UI/来源合同均已闭合，剩余开发项为 0。**

| 开发范围 | 项目数 | 结果 |
|---|---:|---|
| P0：通信正确性、Native 准入/证据、唤醒恢复、迁移与诊断 | 11 | 开发完成 |
| P1：通信服务、事件同步、Native 来源、Orca 接入/委托合同 | 10 | 开发完成 |
| 用户明确启动的 P2：个人状态、草稿/偏好、附件、搜索 | 4 | 开发完成 |

逐项源码路径、文件 SHA、实现说明和需求映射见
[development-capabilities.json](development-capabilities.json)。
P1 的 22 个 API 与 P2 的 13 个 API 均有当前真实服务调用见证，
没有用接口声明代替服务实现。

## 本轮补齐的开发能力

### 原会话冷恢复与持续唤醒：C06 / C07

Codex/OpenCode 将进程传输启动与会话创建分开。恢复必须取得原进程的完整停止证据、
原会话确认、当前签名授权、相同 binding/generation，以及 profile/account/environment
和原 DriverJournal/内核 claim 证据。Codex 仅续接原 thread，OpenCode 保留原数据根并
读取原 session。明确换过会话的 OpenCode 也恢复换绑后的原会话。

Node 重启后可从保留的停止回执和 Core 原始签名计划重建受信上下文。
当前注册、账号、文件或历史不符时保持不可用。未知输入只可重连其原域查询，
在真实原始 ACK 得到确认前继续阻止新输入。

同一条已提交 Message 可保留既往成功生命周期帧，再取得新的原会话恢复计划。
Message、原命令、Core operation 和 Outbox 身份保持，历史可能副作用不会被清空。
Core 当前及归档历史也会阻止丢失 journal 后重建旧命名空间。

相关实现：`runtime/native_restore.py`、`native_restore_origin.py`、
`communication_message_restore.py`、现有 Driver/lifecycle/工厂路径。

### 远端原始 Native 来源：C16 / C21

受信注册可选择本地 DriverJournal 或 `RemoteNativeSourceReader`。
远端读取复用现有签名 TLS readback、原 dispatch 和回执，没有新增来源权威表。
调用方不能提供文件路径、Provider URL 或替代会话。

Core 当前消息 ACL、原 dispatch 和 provider 注册身份包围整个读取过程。
接收端当前技术读取权限与旧发送者的输入权限独立；缓存结果同样重新授权。
返回值只包含经过证据关联的来源引用，Host transcript/control 权限独立保留。

相关实现：`communication_client_native_source.py`、`remote_native_source.py`、
`native_provider_registry.py`、现有 Receiver/transport 与生产工厂授权路径。

### 具体 Orca 接收后端：C17

`ExistingOrcaReceiverBackend` 已接入实际签名验证、prepared 记录和 dispatch 账本。
`OrcaReceiverRouter` 接入现有 prepare/readiness/dispatch/readback 路由。
Host 提供自己的串行最终准入、当前 ownership 和原操作查询回调。

可能进入 Host 前，原验证命令与封存字节保存在原 dispatch 回执中，并保留执行租约。
ACK 丢失后只查询同一 Host operation/epoch/generation；真实原 ACK 可修复同一条回执。
当前会话切换不会改写其历史来源。ACS 不接管 Orca 的 Native Driver/PTY。

接入说明见 `sdk/ORCA-RECEIVER-INTEGRATION.md`。

### P2 服务完整保留并接通

- 个人单调 read frontier、独立未读标记及 notice seen，与 Agent Inbox 消费分离。
- 个人偏好、静音/归档和多设备草稿 CAS，维持 viewer 隔离与冲突语义。
- 二进制附件 reservation/upload/finalize/download，执行 digest、大小、MIME、ACL、
  配额、生命周期及 SSRF/路径边界检查。
- 按当前消息权限过滤的正文全文搜索及稳定分页。

Native 附件转换属于 Host 委托，只有独立证明目标可达和授权后才能声明可用。
新增 Claude/Pi 完整 Driver 是包内条件性扩展，需确切目标环境；不属于这 25 个必核改造项。

## 验证结果及证据范围

| 批次 | 通过 | 跳过 | 范围 |
|---|---:|---:|---|
| `development-final-integration-b` | 76 | 0 | 真实 Core/PG、HTTP/OAuth、生产 SDK、35 API、远端 TLS 来源、恢复工厂、观察权限、重绑、临时安装维护器、旧 MCP 链 |
| `wake-lost-ack-regression-b` | 31 | 0 | 签名 TLS 启动/丢失 ACK、原消息唤醒、重复原会话恢复 |
| `remote-source-current-read` | 28 | 0 | 具体后端、远端来源、独立当前读取权限与缓存撤销 |
| `driver-warm-compatibility` | 219 | 9 | 常规 Driver 启动、输入、ACK、来源/只读权限组件 |
| `final-restore-source-components` | 284 | 1 | 冷恢复、Node 重建、journal/profile/fence、Host/来源组件 |
| SDK / 严格 TypeScript | 210 | 0 | 生产 SDK 与宿主端口合同；类型检查通过 |

这些批次存在重叠，不能相加成一个全量通过数。每批保留原命令、日志、XML 及运行前后
源码 SHA。最终 76 项批次的受测文件前后未变。较早组件批次之后的只读接收器配置和
换会话恢复增量，由后续对应组件及最终 Core/TLS 组合覆盖；差异逐文件列在审计中。

常规 Driver 批次的 9 个跳过为 2 个 POSIX 专属用例和该纯组件批次未注入 PG 的 7 个
观察权限用例；后者在最终真实 PG 组合中执行通过。恢复组件的 1 个跳过是 Codex 参数下
不适用的 OpenCode HTTP journal 场景。最终组合有 2 条 pytest 属性记录格式警告，见原日志。

开发包/checksum、4 项合同导出、改动范围 Ruff、diff 格式、SDK 和严格 TypeScript
共 10 项检查通过，见 [development-static-b.json](development-static-b.json)。
全仓 Ruff 的 6 条既有告警均在 HEAD 未改动文件，另见
[preexisting-lint.json](preexisting-lint.json)。

首次大组合发现 2 项旧夹具分类失败后收束，原记录及聚焦失败栈全部保留。
夹具原先把只读原会话查询计入了“创建次数”；修正后分别记录读取与写入，
仍严格要求一次创建，禁止额外写入，并核对读取的原会话身份。上述 31 项重验通过。

## 安装与源码状态

当前源码已离线构建为 2.3.1 候选 wheel，并安装到独立临时目录。
**191 个包文件与当前源码和临时安装逐文件一致。**
独立安装维护器在客户端进程退出后推进原持久消息的用例也已通过。

候选 SHA-256：
`36852c03bbf157d8fb8c06ab2630dc2b10e969832857bba651688ee2530fcaec`

包位置和逐文件证据见 [package-facts.json](package-facts.json)。
源码位于 `D:/Chatgpt/Agent-collaboration`，分支 `codex/core-cleanup`，
HEAD `19d7881d49ee887315c54c5bc02e0cc424061376`。工作树含原有及本轮未提交内容；
未 commit、Push、部署或改动生产数据/配置。原有研究、工作树和历史证据保留。

## 单列的资格范围

当前改过的 Driver/lifecycle 栈尚需新的实际 Native/版本/平台资格，历史 E3/E4 只按
其原始源码版本保留。本轮 Host 接纳/查询是明确的受控替身，没有安装或实测实际 Orca Host。
物理双机、未测 Shared/restricted/平台组合及 POSIX 完整后代 containment 也不由这些结果推定。

这属于用户排除的验证覆盖面，开发待办为 0。详细资格与旧源码差异见
[qualification-matrix.json](qualification-matrix.json)。本轮真实模型调用数为 0。

当前没有活动测试 runner 或测试数据库租约，开发目标可完成。
