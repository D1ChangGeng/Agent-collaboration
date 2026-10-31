# 默认 Domain 和底层入口退出任务职责

本阶段接续 `9921e6e`，分支 `codex/core-cleanup`。完整目标保持 active。
本地候选由本阶段源码构建；没有 Push、正式发布、生产迁移或远端服务切换。
用户原有 README 和其他未提交资料保留。

## 实际代码与需求

- R02/R30：从默认 `DomainAuthority` 移出 Work、Review、AcceptedState 守卫、
  execution receipt、任务 Attempt、Lease/Effect 和任务 Harness 绑定方法。
  Node/Runtime 登记、身份/授权、命令防重、通信和来源读取仍在正式实现中。
  `EnrollmentAuthority` 的任务/结果登记也退出；历史方法成为测试夹具，
  旧断言继续检验历史数据，夹具不进入 wheel。
- R02/R32：`surfaces.py` 移除旧 payload/dispatch 分支和默认 RecoveryService。
  CLI、stdio MCP、HTTP 的 Schema 与解析器只接受 12 类技术命令；消息业务仍
  通过项目工具完成。旧任务读、任务执行观察、Lease/Effect、结果投影均拒绝。
  `surface_config.py` 接受已有 Effect 配置字段，但不构造旧网关。
- R02/R31：正式 Delivery 的 Work/AcceptedState/任务 Handoff 边界退出；
  `team_policy.py` 移入历史夹具。新旧业务包不能由当前 Domain/Delivery 新建或
  派发到 Native；归档原文与防重事实保留。操作员 scan 排除旧包，dispatch
  在写审计前拒绝旧包，保留实际原记录。
- R22/R32：操作员派发改为读取当前可信接收器，修复构造时容量快照失效；
  审计不再取不存在的 work_item_id。当前消息派发正常，旧包不产生 Native
  Attempt。新安装权限不再添加旧业务权限，移除退役 `acs-human-bridge` entry。
- 测试隔离：个人技能发现范围超出 CODEX_HOME。首次模型复验尝试读取
  这些指引且遭测试策略拒绝，并遇到 Provider 断流。采用官方支持的
  [逐技能配置](https://learn.chatgpt.com/docs/build-skills#enable-or-disable-local-codex-skills)，
  只在测试 home 禁用继承技能；真实 skills/list 读回 51 个、enabled=0。
  未改全局技能或 Desktop 配置，未放宽执行权限。

## 实际验证

| 范围 | 结果 | 材料 |
|---|---|---|
| 当前通信、归档、通知、身份、接收器、适配器和技术入口 | 71 passed / 2 skipped | `current-final.xml` |
| 默认入口与历史包只读 | 17 passed | `kernel-first.xml` |
| 历史夹具保留的旧断言 | 59 passed / 75 skipped | `historical-final.xml`；不是当前任务功能或 Linux 资格 |
| 正式 Factory，独立普通 A/B 实际模型闭环 | 1 passed，159.22 秒 | `native-factory-final.xml`、`native/factory-final/` |
| 当前源码，Windows Codex ↔ 1302-1 OpenCode | 1 passed，122.24 秒 | `cross-harness-final.xml`、`cross/final/`；message_only |
| PostgreSQL pg_dump/pg_restore | 1 passed，4.77 秒 | `backup-restore.xml`、`backup-restore-facts.json` |
| wheel 实际安装及正常公共工具 | 2 条消息、1 条关联回复，零 Work/AcceptedState | `installed-candidate.json`；脚本行为、无模型 |

实际 Native 来自 Windows Codex 0.166.0-alpha.5.1，真实生产 Factory 和
Node/Runtime 登记；A/B 为不同普通身份和上下文。共 2 条自然消息、1 条主动
关联回复、1 次 Native turn/start，WorkItem=0，Collector=false。
跨机 B 是实际 OpenCode 1.18.34，经正常 MCP 自行收信和关联回复；控制器
不转发正文或回复 ID。跨机测试使用回环 SSH 数据库转发和共享隔离 Authority，
不是跨机签名 Receiver 或 Native 自动激活验收。耗时含模型和网络。

wheel SHA256：`6a76d677063b01b97d073afae2e30aa22fe183fba3d84cb04e583780614d987d`。
110 个实际安装的 Runtime/Deployment Python/SQL 文件逐字节匹配本阶段源码，
测试夹具未打包。软件版本仍为 pyproject 原有的 0.1.0，与开发包 v2.33 无映射。

恢复演练的 82 张表行数和摘要相等，原包与主动回复保留；来源及恢复库的旧
Authority 均隔离，新只读代际可读，快照后模拟 Native 效果没有重放。
只移除了本次临时恢复库。夹具原先固定的输出路径已改为每次独立目录；本次
新事实另存，旧证据恢复原始字节。当前证据目录以 Git -text 保存原始字节。

## 保留失败与范围

`native-factory-provider-failure.xml` / `native/provider-failure/` 保存 248.67 秒
超时：Provider 断流时 A 尚未提交 ACS 消息，不计通过。重跑使用新隔离身份
和会话，没有重发可能已经发生的 Native 操作。

`surface-first.xml` 暴露容量快照问题，`operator-fixed.xml` 验证修复。
`historical-fixtures.xml` 的三项失败分别为历史服务夹具尚未迁移及两项已撤回
公开合同的旧期望；历史锁和身份断言保留，公开合同改为明确拒绝。
`historical-bindings-fixed.xml` 与最后整组验证均通过。

`cross-harness-sigterm.xml` / `cross/sigterm/` 保留 OpenCode exit=-15，原因
尚未定位；进程组停止已读回，未将该运行计为通过。下一次加入清理前退出码
记录，在新隔离上下文上完成交换；原始日志、两次源文件清单均保留。

本阶段没有精简默认混合 SQL，没有清理生产存量。部分未绑定历史模块仍在
源码中；下一步继续最小新装存储及显式采用，继而核实重启窗口、跨机 Native /
OpenCode receiver 和受限 Harness。这里不声明所有 WP 或正式 Gate 完成。
