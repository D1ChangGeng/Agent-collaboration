# 等待进程中断恢复与 OpenCode Native 前置修正

接续 `fd6bb4bbb3f9bdc5a09e0a119b8c6f79cf7ade8b`，分支
`codex/core-cleanup`。完整目标保持 active；没有 Push、发布或生产切换。

## 实际代码

- R15/R22/R23：`communication_dispatch.py` 增加有界过期等待租约清理，每次
  最多 64 行，按 Tenant 隔离并跳过被锁行。只处理已过期观察资源，不删除
  原消息、回复、Outbox 或防重事实。默认维护循环运行此清理。
- R22/R26：`project_service.py` 的同请求缓存仍复用原操作与原消息，重试返回
  明确的 duplicate=true；不改写已存初次响应，不额外发送消息。
- OpenCode 前置：`PosixProcessSupervisor` 的读回补齐与现有 Driver 一致的
  root_pid/root_exited/remaining_pids，保留 owned_process_group 和
  subtree_containment=false 的实际边界。未放宽 Shared/Systemd 保护。
- R21：OpenCode native 模式不再订阅后台 /event SSE；发起和状态检查保留
  有界 HTTP 读回。restricted 历史参考模式的原断言与保护不改为 Owner 声明。

## 运行与证据

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 通信、持久等待、归档、权限和存储回归 | 83 passed / 2 skipped | `regression.xml` |
| OpenCode Driver、HTTP 边界与读回竞态 | 90 passed / 3 skipped | `opencode-regression.xml`；显式合成 HTTP Peer |
| 原生模式不订阅执行事件 | 1 passed | `opencode-owner-events.xml`；合成 Peer |
| 实际 Linux 自有进程组生命周期 | 1 passed | `posix-real.xml`；本机 WSL、真实 PID/birth/所有权 |
| OpenCode 1.18.34 实际 Session API | 创建/读回/删除，零模型 | `opencode-api/facts.json` |

`test_communication_restart.py` 使用 4 个真实 stdio MCP 服务进程和真实 PG。
普通 A 发信并进入真实等待后，测试通过 SDK 所持的进程句柄强制终止 A。
确认进程退出及孤立租约尚在后，B 通过自己的正常 MCP 入口回信。
结果通道已关闭，没有将它当作模型已读；回执保留 model_consumption=unconfirmed。
新 A 进程从 Inbox 读到回复，连续两次等待得到同一准确回复。新 B 连接用
原 client_request_id 重试，返回同一消息和 duplicate=true。最终只有 2 条消息、
1 条关联回复，受控 Native Driver 调用为零；旧租约自然过期后由默认维护回收。
这是进程/数据库恢复验证，Agent 行为由脚本驱动，没有调用模型。

`first.xml` 保留新进程重试时 duplicate 标记未更新的首次失败；消息操作本身
已复用，缓存响应标记随后修正。`fixed.xml` 的同请求并发、进程重启和清理
检查均通过。活租约与原消息不被清理，有界批次断言保留。

远端 API 探针运行于独立 /tmp 和 HOME/XDG、随机回环认证端口，只对本次
自有 Session 操作，没有请求模型。实际 API 可保存并读回 ACS binding metadata、
agent、model 和真实 Session ID；不把该探针当作正式 Driver/Receiver 资格。
原正式 checkout 与默认配置保留。

## 未完成与授权边界

尝试将当前 Runtime 的 .py/.sql 源码副本 SCP 到 1302-1 独立 /tmp，以继续
正式 Driver 验证时，自动审批明确拒绝：认为源码外发的具体内容和目的地尚缺
明确授权。未通过其他方式绕过；授权问题已向用户异步提出。
本机/WSL 未发现可直接运行的 OpenCode 程序，仍完成了不受影响的本地回归。

因此本阶段没有宣称 OpenCode Native 端到端通过，没有正式 OpenCode Receiver
Factory 的实际模型验收，也没有跨机签名 Receiver 自动激活资格。
下一步在相应授权和环境允许后继续正式 Driver 与接收器；其他需求核实继续。
