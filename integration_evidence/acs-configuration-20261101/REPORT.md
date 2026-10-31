# 配置提交与 Native 准备的接收绑定一致性

接续 `6f144e3a35e3bcdb3ef67d5074dcd47dcefc6235`，分支 `codex/core-cleanup`。
完整目标仍在继续。没有生产迁移、服务/正式 checkout 切换、Push 或发布。

## 实际问题与实现

原实现提交接收端 A 后，在准备阶段重新读取最新配置；并发管理调用改为
B 且关闭准备时，较早调用仍会准备 B，并把 B 的 Session 当成自己的结果。
`before.xml` 复现该错误，同时保留无关显示名更新仍可合并的正例。

现在配置提交时解析实际接收位置，返回 `endpoint_id` 和 `binding_revision`。
准备前后检查该选择；发生改绑或绑定版本变化时，报告
`configuration_changed`，不提供“当前 Session”声明。准备已开始后才改绑的
场景保留 `preparation_observation`，承认已发生的观察，不伪造回滚。
无关字段变更不使接收选择失效。

没有新表、配置生命周期或必须由模型维护的修订参数。目录更新为
`acs-p2-mcp-tool-contract/10`；正文结果 revision 2 和 Message 协议不变。
输入仍复用现行工具；`if_unchanged` 的属性期望在真实事务中校验。

主要关联 R03/R06/R08/R26/R32。涉及
`runtime/communication_management.py`、`communication_tools.py`、公开目录、
使用说明、测试和 CI。

## 实际验证

| 范围 | 结果 | 材料 |
|---|---|---|
| 改绑竞态与无关字段合并 | 先 1 failed / 1 passed，修正后 2 passed | `before.xml`、`after.xml` |
| 独立管理调用的属性合并/冲突、绑定版本、准备期间变更 | 6 passed | `races.xml`；真实 PG，Native 观察明确为夹具 |
| 配置、身份、通信及 Native 工厂回归 | 50 passed / 6 skipped | `regression.xml` |
| 当前源码真实默认入口双模型 | 1 passed，250.07 秒 | `codex-74e9625d91ac45f69210414cdc0c7ef7.xml`、`dual-model/` |
| 新 wheel 实际独立安装 | 106 文件与源码匹配、46 表、2 消息/1 回复 | `installed-candidate.json`；脚本，无模型 |
| 同一快照的 OpenCode Driver 复核 | 49 passed，36.18 秒 | `opencode-recheck.xml`；合成 HTTP Peer |
| 同一快照的完整默认组件复核 | 887 passed / 729 skipped，159.62 秒 | `ci-components-linux-recheck.xml`；数据库/模型依赖关闭 |

双模型使用已有授权的 Windows Codex A 和 1302-1 OpenCode B Owner 隔离环境。
配置返回提交的 remote-opencode-endpoint、绑定版本 1 和实际读回的同一 Native
Session。随后双方经自己身份的普通 ACS MCP 收发；默认 stdio 后台维护器
负责实际投递，评测器派发次数为 0。1 次 prompt_async、2 消息、1 条精确回复，
Work 表不存在；Collector/SSE 没有启用。Native ACK 未确认不阻止主动回信。
退出后自有进程组为空。源码清单覆盖 108 文件并与当前树核对。

CI 默认完整组件范围的第一次复核为 886 passed / 729 skipped / 1 failed，
保留于 `ci-components-linux-current.xml`。失败是 OpenCode 取消并发测试的
2 秒 abort 入口等待未满足；没有修改该测试时限或放宽串行化判据。
同一源码副本的 49 项 Driver 测试与完整组件复核随后通过，结果单独保留。
首次失败未复现，原因尚未确立；不能把复测通过写成已修复根因。
这是本机 Linux 隔离运行，不是远端 GitHub CI；729 项跳过不计能力通过。

当前候选 wheel SHA256：
`8d9a9f6578ff23d4898a2bc77da46b10f862ce7b2b6a044c0f3cdb89a1197eaa`。
软件版本沿用 `0.1.0`，与文档开发包版本分开。

结束前只读核对隔离测试库没有非系统 Schema 或恢复数据库；1302-1 正式
checkout 仍为干净的 `codex/runtime-p2-execution`，没有切换正式服务。
现有 README 中英修改的原始哈希保持不变。证据摘要见
`source-state.json`、`evidence-manifest.json`。

## 限制与后续

可控竞态通过不等于所有真实 Harness 的配置竞态都已资格化；本阶段真实
模型覆盖正常配置接入和默认投递路径。Shared OpenCode、Systemd、反向物理
Native、故障替换及更大规模负载没有由本阶段证明。完整 R01–R34 审查仍需
继续，生产切换与发布保留授权边界。
