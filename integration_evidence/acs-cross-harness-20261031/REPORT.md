# Windows Codex ↔ 1302-1 OpenCode：真实普通 Agent 通信

代码基线 `7143ef20c5cde4e12a77ee04f63e75813597e18e`，
分支 `codex/core-cleanup`，加本阶段 `runtime/communication.py` 的空过滤修复。
实测源文件见每次运行的 `source-files.json`，传输和运行期间逐文件核对。
这是一项 WP03/WP06 增量；完整目标仍在继续。

## 实际改动

`_list_messages` 将可选 `with=""` 与省略统一为无过滤，SQL 条件和游标查询
身份同时保持一致；非空地址仍严格校验。真实 OpenCode 自动填充空字符串时，
此前会得到错误的空 Inbox。新增真实 PostgreSQL 回归验证 Inbox、历史、
跨省略/空值分页、指定联系人过滤和无效非空地址。

新增可显式启用的 `test_communication_cross_harness.py` 与远端 actor 夹具：
本机 Codex 和远端 OpenCode 是独立模型上下文、独立普通 engineer 身份。
配置者凭据没有交给模型。A 提交后才启动 B；控制器不转发正文、不提供回复
ID，也不将终端结果投影为消息。B 从正常 Inbox 读取并自行调用 send_message。

远端源码复制到唯一 /tmp 目录并创建独立 venv；正式 checkout 未切换。
OpenCode 的 HOME/XDG 仅为子进程设置，实际读回只有测试 ACS MCP、指定
Provider、零插件；其他工具被显式拒绝。用户明确授权的 WSL Provider 凭据
通过 SSH stdin 传入，实际密钥不写配置或参数，不输出。数据库 SSH 转发只绑
回环地址；这是共享 Authority 的通信测试，不是签名 Receiver Native 传输。
远端进程组按本次启动的 PID/birth/归属停止并读回；没有按名称终止其他进程。

## 实测证据

| 验证 | 结果 | 证据 |
|---|---|---|
| 首次真实模型交换 | 失败，2 条消息、0 条回复关系 | `exchange-first.xml`、`b05b174295ea467cab25906c1f6a86cb/` |
| 空过滤 PG 回归：修复前 | 2 failed | `empty-peer-baseline.xml` |
| 空过滤 PG 回归：修复后 | 2 passed | `empty-peer-fixed.xml` |
| 修复后真实模型交换 | 1 passed，84.56 秒 | `exchange.xml`、`e7118c0fe90e42238b0d1393561d2226/` |
| 当前通信 PostgreSQL 回归 | 34 passed / 2 skipped | `core-regression.xml`；两个模型测试按显式启用策略跳过 |

改动的通信实现和跨机夹具 Ruff / 编译检查通过。证据打包前逐文件核对测量源码，
并在内存中检测获准 Provider 密钥没有出现在留存材料中。

成功运行实际产生 2 条自然消息、1 条主动关联回复、0 个 WorkItem，全部使用
message_only，受控 Native Driver 调用为零。A 得到了仅 B 初始上下文知道的
随机标签。B 是实际 OpenCode 1.18.34，本机是 Codex 0.166.0-alpha.5.1。
时长包含模型和网络，不是 ACS 传输延迟。工具日志中的 start/completed 是
同一调用的两个事件，不能当作两次发送。

首次失败中，B 的 `with=""` 隐藏原请求；B 另发未关联信息，A 的等待没有
错误地满足。完整关系断言保留并失败，没有让提示词或测试控制器补造 reply_to。
`empty-peer-first.xml` 记录本机 sandbox 无 TCP 权限的启动错误，不计产品回归。
随后在获准网络环境中复现产品缺陷并验证修复。

远端正式仓库仍为干净的 `codex/runtime-p2-execution`，HEAD
`e900773fc39d61559a128e7438337ca39d12c02c`。用户原有两个 README 字节摘要
保持不变。未 Push、未更改默认 Harness 配置、未迁移生产或切换现有服务。

## 声明边界和继续工作

跨机器 Codex↔OpenCode 的该 message_only 方向有真实工具证据。OpenCode
Native receiver、反向发起、跨机签名 Receiver 自动激活、Shared 受限 Harness
资格及等待进程重启窗口尚未由本次验证。默认 Domain/混合存储仍须继续退出
旧任务职责；不能把本阶段称为全部 WP 完成或正式发布验收。
