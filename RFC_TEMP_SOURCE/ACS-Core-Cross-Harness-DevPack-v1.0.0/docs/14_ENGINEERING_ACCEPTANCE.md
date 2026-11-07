# 14｜工程质量与验收

## 测试分层与事实标签

L0 `package_validation`：本包引用、schema、fixture、OpenAPI 引用、映射和 Python 类型的静态一致性。
L1 `unit`：纯状态准入、adapter 映射、错误分类、schema、query/reducer。
L2 `controlled_integration`：真实 PostgreSQL/Node journal/HTTP/stdio，多进程故障和并发，Provider 为明确标注的受控 double。
L3 `native_protocol`：实际安装二进制/Session/接收工厂与权限，真实 handoff 和 readback，不要求以模型质量作对比。
L4 `independent_model_e2e`：独立 Agent 通过自己的 MCP 发信和显式 reply_to，禁止测试器代答或手动 dispatch。
L5 `host_integration`：实际 Orca Host/插件或原生 bridge + headless consumer，明确上游版本/主机/能力，非截图视觉验收。

L0–L2 不能代替 L3–L5。未授权的生产测试不允许。某环境 unavailable/未执行就记 blocked，不计为 pass；期望 unsupported 的负例需要真的执行并验证无副作用才可 pass。

## 必测故障窗口

- Authority commit 之前/之后、Outbox dispatch 之前/之后、Receiver durable intent 之前/之后、Provider 接纳之前/之后、ACK 落盘之前/之后、回信事务之前/之后分别终止进程。
- 无 ACK 但真实回复已到；无回复但 Native 完成；同消息跨重复请求/新连接重放；同键不同内容。
- prepare 期间 rebind、lease 到期旧 worker 仍运行、旧 epoch Late ACK、Provider session replacement、同 principal 多 Slot。
- busy→ready 时消息与人工输入竞争、审批 blocker 和 pending draft、native queue 已有卡片后进程重启。
- snapshot 读和 event 到达并发、SSE 重连重复事件、游标过期、读权限撤销、慢消费者、客户端掉线后命令结果未知。
- 附件 finalize/send 竞争、digest 不符、跨 namespace 下载、原生文件 path 不可达、UTF-8 小预算。

每项定义在 `tests/scenarios.json`；GIVEN/WHEN/THEN 可直接转为目标测试，不是新一轮研究实验。

## 最低实际验收链

在隔离 namespace 启动已安装 Core；使用两种现有 Harness 中真实 A/B 完成通信→自主回复→等待恢复。额外终止一个 wait 进程，新受信入口续等同 handle；message_only 保持零激活；撤销身份阻止新的 Native handoff。保存真实请求/receipt/DB 关系/Node journal/版本/命令/退出码。

运行 headless HTTP consumer 在真实服务上完成 profile、snapshot、分页、发送、SSE断线replay、个人未读、附件、native link 和错误恢复。native provider contract fake 可覆盖类型分支，但不能宣称实际 Orca 已接通。

## 测试断言方向

主断言是可观察效果与不变量，不是函数是否被 mock 调用、文件是否存在、测试 fixture 能读回自己。允许 Adapter double 精确构造不可复现竞态，但报告必须写清楚 seam。等待超时不计通信失败；真实 endpoint 无法连接也不能被重试后一次通过掩盖。

## 可重复性

记录源码 commit/tree/dirty patch digest、产品包版本、实际 executable/version、host/os/account namespace、传输/授权模式、配置摘要、观察时间、原始日志 checksum。禁止把旧报告统计数累加为新候选通过数。保留初次失败、修复和复测。

## 完成判据

每个 R 至少有正反/故障用例；所有 P0 用例与旧语义回归通过；新 public endpoint 必须有 auth、分页/预算、错误和幂等测试；每个 UI feature 有 real service 或 authority-delegate 测试；宣称的 Adapter capability 都有适用版本证据。缺 native 环境可交付代码，但不能写完整资格验收通过。
