# 物理跨机器签名 Native 通信与 Core 2

接续 `4fa2d4b6cac81d8eda6b121bfdd6eed2d81bd4f2`，分支 `codex/core-cleanup`。
本阶段跨越 2026-10-31 / 2026-11-01；完整工程目标仍在继续。
没有 Push、生产迁移、正式 checkout / 服务切换或发布。

## 实际代码与发现

- 真实签名投递发现 `delivery_transport_admissions.accepted_revision` 仍有
  旧任务 NOT NULL 约束。Core schema 2 允许自然消息保留空值；签名回执模型
  和发送身份同步允许空值，没有构造任务版本或使用 0 代替。
- 显式采用只识别已知 Core 1 的 LF/CRLF 摘要，保留行和签名 JSON，更新
  元数据版本。未知摘要、缺少权威账本/防重索引仍拒绝；正常启动只读校验。
  冻结的 Core 1 SQL 在测试夹具内，不进入 wheel。
- 真实 Native ACK 超时读回暴露阶段与终态混用：`runtime_dispatched` 等接收
  阶段现在映射为投递 `uncertain`，保留原签名和派发栅栏，不重开 Native。
- 配置的接收端离线现在进入现有运输故障/有限重试分支，不让普通异常遗留
  一个无结果的 delivering 状态。
- 可达接收端的 Native 状态读回失败返回 `unknown`。OpenCode 的时钟/当前
  读回未确认时不提供确认的 Session 引用；真实 Runtime 撤销仍拒绝。
  没有放宽入场授权、时钟范围、监听所有权或派发防重检查。
- 发送端私有配置增加 `request_timeout_seconds`，1–120 秒、默认 30 秒。
  实测 Native 健康查询约 10–11 秒，原先固定 5 秒会误报不可达。
- PostgreSQL CI 入口增加 Core 升级、无任务签名链和 OpenCode 工厂验证。

涉及 `runtime/communication_storage.py`、Core SQL、`domain.py`、
`receiver_models.py`、`sender.py`、`receiver_delivery.py`、
`machine_connections.py`、`surface_config.py`、`remote_endpoint.py` 和
`runtime_deployment/receiver_opencode.py`，以及对应测试和使用/采用说明。
主要关联 R02/R06/R08/R12/R18/R21–R24/R26/R31/R32/R34。

## 实际验证

| 范围 | 结果 | 证据 |
|---|---|---|
| Windows A → 1302-1 OpenCode B，脚本普通 A、真实模型 B | 1 passed，186.74 秒 | `scripted-a509ceefbaf04732b8860d8e945a9bcb.xml`、`single-model/` |
| Windows Codex A ↔ 1302-1 OpenCode B，独立真实模型 | 1 passed，225.32 秒 | `codex-d2fdce1d554b48bd92b9a18125315d78.xml`、`dual-model/` |
| Linux 签名协议、空任务版本、ACK 未定、离线重试、时钟 | 145 passed | `final-protocol.xml`；Native ACK 明确为夹具 |
| 工厂状态 unknown 与撤销、纯状态查询 | 11 passed / 3 skipped | `health-regression.xml`；合成 Native 明确标记 |
| 私有 Linux 源码副本的 CI 默认 Runtime 全范围 | 887 passed / 709 skipped，0 failed | `ci-components-linux-current.xml`；未开启模型/DB 条件，Systemd 不具备配置资格 |
| Core 2 新装、旧版本显式采用、未知摘要和账本保护 | 17 passed / 120 skipped | `core-v2.xml`；Windows 的 POSIX 协议跳过项已在 Linux 单独执行 |
| Core 2 通信/Driver/配置等回归（状态细分修正前） | 162 passed / 14 skipped | `final-components.xml`；随后状态修正由上面两组及真实模型重验 |
| 同请求内容冲突判据的故意错误变体 | 正常通过、变体预期失败、恢复通过 | `mutation/`；只修改本地副本 |
| 最新 wheel 的实际独立安装、公开工具收发 | 106 文件匹配、46 表、2 消息/1 回复 | `installed-candidate-current.json`、`installed-smoke-current.py`；脚本、无模型 |

直接在 WSL 的 Windows 挂载目录运行 CI 默认范围，结果为 889 passed /
682 skipped / 25 failed，保留于 `ci-components-linux.xml`。其中 6 项被源码
文件的 POSIX 所有权/写权限保护拒绝，2 项仍要求已撤回的任务命令，17 项
缺少实际 Systemd 策略属性。后者环境为 Systemd 249，实际 Service 接口不
暴露所需 ExitType；没有删除生产校验。当前测试先独立探测该能力，不具备时
明确 skipped，不能据此宣称 Systemd 已验收。通用传输 JSON 测试改用现行
技术命令，并验证旧任务命令不在公开集合。

第一次 Linux 副本复核还发现 7 项测试准备问题，保留于
`ci-components-linux-private.xml`。已补齐历史夹具需要的 Management Root 和
独立 Git fixture，缩短 Unix socket 的临时路径，并将 Systemd 能力前置用于
该文件的另一处直接实例化。未修改生产权限或策略校验。
最终同字节源码置于 owner 私有 Linux 文件系统执行完整默认范围：
887 passed / 709 skipped，0 failed，160.35 秒。结果及摘要位于
`ci-components-linux-current.xml`、`linux-source-snapshot-current.json`。
Git 仅为该隔离副本的本地测试仓库，没有远端，不能冒充正式 checkout 的 HEAD。

双模型 A 为 Windows Codex CLI `0.166.0-alpha.5.1`，B 为 1302-1 的
OpenCode `1.18.34`。双方身份分别绑定普通 engineer Slot；接收端的技术
观察者身份另行登记。双方运行 Owner 部署策略，没有共享模型通讯凭据。
第三方 Provider 使用用户已明确授权的现有凭据，仅在测试进程环境中注入。

传输为 SSH 环回转发内的端到端 TLS，固定证书指纹，并使用真实 Authority
签名接纳、Node 签名回执、PG 和接收端 SQLite。SSH 不代替 Receiver 协议。
远端只收到已授权的 `.py/.sql` 源码副本；公有工具合同从远端已有文件通过
当前采用函数生成，并核对正常通信描述/输入/权限与本地一致。

A 自主发现联系人并调用正常 ACS send/wait；B 从真实 Native 输入获得消息，
使用自己的 ACS MCP send 回信。评测器只驱动已提交操作的正常 Dispatcher，
不传递正文、回复句柄或模型输出，不写库代发消息。
每轮有 2 条消息、1 条精确主动回复、1 次 prompt_async，Work 表不存在。
没有 terminal Collector、后台 SSE 或 Native final 回复投影。

两轮 Native 派发结果均为 `uncertain`，但 B 的主动回复独立满足 A 的等待。
回复读回后 B 的 Native 状态仍为 busy；这正是回复与模型终态分开的事实。
同操作未重开 Native。退出后根进程及自有进程组均为空；没有据此宣称
subtree containment 或 Shared 资格。

脚本 A 交流阶段墙钟约 95.77 秒，双模型交流阶段约 136.16 秒，均包含原生
发起、网络、模型/Provider 及工具调用。准备、Native 健康读回、整体测试时间
分开保留；这些数值不冒充纯 ACS 运输延迟或模型计算时长。

最新候选 wheel SHA256：
`59a148cbca8903c6f8da1f16887bc3c4fb2b052c40fc86b6eb3597142cdbbf5a`。
软件版本沿用已有 `0.1.0`，与文档包 v2.33 分开。该安装验证不等于远端
安装型 `acs-receiver` 入口或正式服务切换验收。

## 保留失败与未验证范围

各次原始 XML 保留。代表性的原始材料在 `failures/`：空任务版本写库失败、
派发阶段误写终态、MCP 启动和时钟观察失败。隔离启动包装器曾命名为
`mcp.py`，遮蔽 SDK；已更名为 `acs_b_stdio.py`，临时追踪已移除，发模型
之前新增真实 MCP connected 检查。不会把“模型说不能访问工具”的轮次计为
通信成功。Native 状态查询的 unknown 属于其真实范围，不能冒称已就绪。

当前模型证据限于上述 Owner 组合和已记录环境。OpenCode → Windows Codex
方向的物理 Native 发起、Shared OpenCode、Systemd/故障替换、远端安装入口、
更广泛负载以及生产迁移和发布没有由本阶段证明。
完整 R01–R34 的最终逐项审查仍需继续。
