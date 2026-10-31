# 默认入口后台投递、公平调度与已知 ACK 恢复

接续 `dced06be3c88c914b1c4cea871b8008d24a0d03f`，分支 `codex/core-cleanup`。
完整目标仍在继续；没有 Push、生产清理、服务/正式 checkout 切换或发布。

## 实际实现

- 默认维护器从串行整批处理改为最多 4 个在途运输操作，按到期时间与原始
  创建顺序选取，排除本入口已在途消息。一个慢 ACK 不挡住独立联系人；
  单条异常不再中断整批，异常/忙碌操作沿原身份退让已有重试间隔。
- 没有新增表或任务对象。既有消息锁、Slot 锁、已提交派发标记仍决定能否
  Native；调度不重解释正文、不合成回复、不观察模型终态。
- Dispatcher 的未分类 Adapter 异常按真实派发标记分类。发起前沿既有技术
  尝试预算处理；可能已发起时保持未确认。可信读回已有 Native ACK 时采纳
  既有事实并结束同一尝试，不能为丢失外层结果而重开尝试。
- 真实双模型测试的 Codex A 改用正常 stdio 入口的默认维护器，接收绑定与
  私有签名引用来自隔离服务配置。评测器仅读已提交状态，不调用 Dispatcher
  或恢复命令，不把正文/模型输出转交 B。
- PostgreSQL CI 增加 `test_communication_maintenance.py`；使用说明记录四个
  在途上限、异常隔离和已知 ACK / 主动回复的不同含义。

主要关联 R15/R18/R21–R26/R32/R34。涉及
`runtime/communication_dispatch.py`、`runtime/delivery.py`、对应测试、CI 和
`docs/runtime/COMMUNICATION.md`。

## 证据与判据

| 范围 | 实际结果 | 材料 |
|---|---|---|
| 原串行维护器的首页/慢 ACK 阻塞 | 2 项复现失败 | `before.xml` |
| 调度修正后的初始两项检查 | 2 passed | `after.xml` |
| 未分类结果、资源上限、原消息保留 | 6 passed，16.55 秒 | `final-maintenance.xml`；真实 PG/SQLite，Native 为明确夹具 |
| 已保存 ACK 但外层结果丢失 | 先错误 retry_wait，修正后同次 delivered | `known-ack-before.xml` 与上述六项中的配对检查 |
| 广范围消息/通知/权限/投递/存储 | 146 passed / 3 skipped / 5 failed；失败项已核对并修订 | `final-regression.xml` |
| 修订后投递及真实进程崩溃范围 | 58 passed / 1 skipped | `delivery-fixed.xml` |
| 私有 Linux 同字节副本的 CI 默认组件范围 | 887 passed / 715 skipped，0 failed，176.47 秒 | `ci-components-linux-current.xml`；模型/DB 条件另验，Systemd 配置不具备条件 |
| 默认 stdio 入口独立 Codex A ↔ OpenCode B | 1 passed，205.68 秒 | `codex-97c28b146d634c6db92bfd90f52eaa96.xml`、`dual-model/` |
| 新 wheel 实际独立安装 | 106 文件与源码匹配、46 表、2 消息/1 回复 | `installed-candidate.json`；脚本、无模型 |

默认组件范围使用 `linux-source-snapshot-current.json` 中记录的独立本地
源码/Git 测试副本，未改变正式工作树权限。带 PG 的六项并发/故障检查和
真实模型分别运行；不将 skipped 计作通过或合并冒充未执行范围。

双模型沿用已获授权的 Windows Codex 与 1302-1 OpenCode Owner 隔离环境。
双方使用自己身份下的普通 ACS MCP；B 的答案只存在于其初始上下文。
有 2 条消息、1 条精确主动回复、1 次真实 prompt_async、1 个投递尝试；
Work 表不存在，Collector/SSE 均未开启。评测器派发次数为 0，派发来源记录为
`default_stdio_maintenance`。Native ACK 未确认时，B 回信仍满足 A 等待。
退出后根进程与自有进程组均为空。源码清单覆盖 108 个文件并与当前树核对。

交流阶段墙钟时间包含模型、运输和工具调用，不冒充纯模型或纯 ACS 延迟。
没有把 callback 夹具、状态字段、默认入口代码存在或模型自述当成真实验收。

## 保留失败与测试修订

`regression.xml` 和 `budget-isolated.xml` 保留预算控制点的首次失败：原控制点
是 LocalNode 已明确归类为永久拒绝的 Driver prepare。未改变该合同；预算
测试改在真正未分类的 Adapter 边界注入错误，配对验证 3 次技术尝试及原文
保留。`classification.xml` 记录这一步的 5 项通过。

广范围中的 3 项旧测试曾在可信 ACK 已知后仍期待第二次尝试。现在保留
已知 ACK 一次完成的判据；未确认场景显式使用没有 ACK 的 callback 夹具，
继续证明换 Node 也不能重发。另 2 项历史任务崩溃测试的子进程误用了现行
通信 Service，改为明确冻结的测试 Service；没有恢复生产任务入口。

当前候选 wheel SHA256：
`179d55666897fafe6d620d32b960f186ecf678e5e291b10a6cf081af4ae7d267`。
软件版本仍为既有 `0.1.0`。旧候选和原始测试材料保留。

## 尚未验证

本阶段未资格化 Shared OpenCode、Systemd、反向物理 Native、故障替换或
大规模负载；不因并发上限检查通过就声称生产吞吐量。更广支持矩阵与完整
R01–R34 审查仍需继续。生产迁移、切换和发布保留其授权边界。
