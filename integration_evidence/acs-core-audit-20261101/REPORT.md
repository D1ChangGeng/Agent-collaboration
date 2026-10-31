# 通信核心交付复核与干净 checkout 修正

基线 `f6195bf25d7b6a6fb1c2df3c211028787b2eb29f`，分支
`codex/core-cleanup`。本阶段接续已有真实工程实现，核对开发包现行六份 SPEC
及 R01–R34；不修改开发包原始账本，不把文档映射算作运行通过。

## 实际修改

- 中英文 README 和 GETTING-STARTED 的普通流程改为联系人、自然消息、
  主动关联回信及 Inbox 续接；架构图反映当前消息核心。清楚区分本源码候选与
  已发布 v1.4.0，保留既有 Release 安装说明，不冒称升级已完成。
- `docs/runtime/COMMUNICATION-STATUS.md` 逐项列出 34 项需求对应源码、机制
  验证、真实模型方向和未资格化范围，连接不同源版本的历史证据。
- `runtime_tests/test_communication.py` 的 stdio 证据输出改用 `tmp_path`。
  原测试依赖未跟踪的历史目录；在干净 checkout 中，所有收发断言已完成，
  最后写证据却抛 FileNotFoundError。现在不覆盖旧阶段证据，也无需旧目录。
- `tests/test_machine_install.py` 为每例建立独立安装根目录。原预览用例读取
  WSL 已有安装绑定，与夹具中的模拟主机不符而失败；测试与真实主机状态
  现在隔离。异机绑定必须拒绝的原断言保持，生产 Bootstrap 没有修改。
- CI 的 PostgreSQL 范围加入已有的 `test_communication_restart.py`，覆盖
  实际等待进程退出、原句柄补读、相同请求键重连防重及有界租约清理。

你已有的 README 中英文各 5 行 Client 设计链接保留在未暂存区。本阶段采用
独立 index blob 暂存自己的说明变更，逐行核对未暂存内容恰好为原增补；
没有整体暂存、覆盖或代提交它们。详见 `user-readme-preservation.json`。

## 实际运行

所有运行在本机新的 owner-private Linux 副本和指定隔离数据库进行。脚本只
复制明确的已跟踪源码/测试/文档，使用独立 Git 夹具提交，无远端；不是 GitHub
托管 CI 运行。未启用模型的测试不计真实 Agent 验收。

| 范围 | 结果与说明 | 证据 |
|---|---|---|
| 初次声明的 CI PostgreSQL 范围 | 355 passed / 8 skipped / 1 failed，401.49 秒；唯一失败是 stdio 历史目录输出 | `postgres.xml`、`postgres.stdout.txt` |
| 完整源码副本 Skill 校验 | passed | `complete-snapshot/skill.stdout.txt` |
| 完整源码副本工具链 | 232 项，1 error；主机已有安装状态干扰预览 | `complete-snapshot/toolchain.stderr.txt` |
| 安装测试隔离修正的独立副本 | 232 项全部通过，原断言保留 | `toolchain-isolated.stderr.txt`、`toolchain-isolation.json` |
| Gate 工具链 | 123 项通过，52.42 秒 | `complete-snapshot/gate-tooling.stderr.txt` |
| Receiver 实际安装器 | provision 成功，安装入口复核一致，OpenCode Factory 绑定成功，106 源文件匹配 | `receiver-install.json` |
| 最终 Skill 与完整工具链 | Skill passed；232 项工具链全部通过，9.91 秒 | `final/skill.stdout.txt`、`final/toolchain.stderr.txt` |
| 最终 stdio 收发及实际进程中断恢复 | 3 passed / 0 skipped，12.20 秒 | `final/postgres.xml`；真实 MCP/PG，脚本 Agent |

最终修正后的 Skill、232 项工具链及 stdio/进程中断恢复的针对性结果单独
存于 `final/`。没有对未受修改的 355 项 PostgreSQL 机制反复重跑凑总数。
本阶段没有改 Runtime 源码；其 108 文件真实模型清单和 106 文件 wheel 清单
继续逐项核对，因此无需把文档和测试目录修正说成又做了一次模型实验。

安装测试使用当前候选 wheel：
`8d9a9f6578ff23d4898a2bc77da46b10f862ce7b2b6a044c0f3cdb89a1197eaa`。
在新的 WSL 私有临时目录运行生产 `receiver_provision.provision`，使用离线
ensurepip 建立独立安装工具；依赖解释器通过受支持、摘要绑定的 wrapper
引用现有测试依赖。`acs-receiver --verify-install` 与 provision postflight
完全一致，`--factory-binding --factory-reference runtime_deployment.receiver_opencode:callbacks`
使用已安装入口取得真实安装绑定。未启动该接收服务或请求模型，不能把它
计为已安装服务的 Native 端到端验收。

## 失败的归因与保留

最初的隔离副本漏带 assets/scaffold、references 和 VERSION，导致 Skill 校验
及工具链 15 failures / 97 errors。修正副本文件集后，Skill 通过，工具链只剩
上述真实主机状态干扰。原始输出和 `run.json` 保留；补齐资料是测试现场修正，
不是产品代码修复。完整副本及最后副本具有各自源摘要，不改写前一快照。

配置阶段首次取消并发失败在同源 Driver/完整组件复核中未复现，根因仍未定位，
记录见 [配置阶段](../acs-configuration-20261101/REPORT.md)。本阶段没有放宽其
2 秒判据，也不把后续通过宣称为根因已修复。

## 可声明范围和未验证能力

源码中的核心通信机制及当前已测方向见
[支持记录](../../docs/runtime/COMMUNICATION-STATUS.md)。已取得独立模型的
Windows Codex→1302-1 OpenCode 签名 Native 与默认入口自动投递证据；本阶段
复用其明确源清单，没有冒称新模型运行。消息没有 Work 依赖、主动回复由 B
自己正常工具提交，Native terminal 不代答。

相反物理 Native 方向、Shared OpenCode/Systemd 受限 Profile、真实模型的所有
故障窗口、大规模持续负载、已安装 Receiver 服务完整启动主链和生产升级均未
由本阶段证明。没有 Push、正式服务/远端 checkout 切换、生产清理或发布。
后续部署与扩大支持声明分别需要相应现场验证和授权。

结束前再次核对：测试库没有非系统 Schema 或恢复数据库；1302-1 正式
checkout 是干净的 `codex/runtime-p2-execution`，HEAD 仍为
`e900773fc39d61559a128e7438337ca39d12c02c`。文件摘要、源码差异边界与
凭据未归档检查见 `source-state.json`、`evidence-manifest.json`。
完整工程目标仍继续；下一切片是隔离安装后的 Receiver 服务启动与 Native
主链验证，不能把本阶段安装入口校验冒称该能力已通过。
