# 03｜通信内核的原位替换

本文件是替换范围的主规范。禁止只新增一条 ACS send 入口，却让原生自动协作继续在旧邮箱中运行。

## 三个平面必须分开

A. **用户—原生 Agent 工作平面**：普通 composer、stop、steer、模型、审批、工具、终端输入。继续走原生宿主，不强制转为 ACS 通信。

B. **Agent—Agent 通信平面**：自然发信、reply、inbox、历史、主动唤醒、跨主机转递。必须使用 ACS。

C. **可选任务监督平面**：Run/Task/Dispatch、依赖和 Gate。可保持现有界面和状态机，但通过 B 交流。Task 完成只由其受权生命周期操作判定，不从任意消息正文推断。

把“通信内核替换”扩大成改写所有 WebSocket、RPC、PTY 或 Native Session 是错误实现。

## 入口逐项替换

详见 `contracts/message-paths.json`，工作完成时每行必须指向实际新调用链。

| 现有行为 | Porpita 实现 |
|---|---|
| 普通 ACS MCP send/reply_to/wait | 原样使用，更新每个会话的可信绑定与上下文 |
| `orchestration.send` 普通消息 | 保留 CLI/内部调用外形，可信解析 caller/target 后调用 ACS；返回 ACS handle 的兼容映射 |
| `ask` / `reply` | 上层保留 question/option UI；通信采用 ACS 原消息与 reply_to。等待观察原 handle，不再创建旧 inbox 消息 |
| `check` / `inbox` / 历史 | 从 ACS 历史取数；旧“处理过”是工作流消费者私人前沿，不改变 ACS 读不消费语义 |
| group send | 在上层解析当时可见组成员，生成逐目标 ACS send；每条有独立结果，展示部分成功，重试不重复成功项 |
| `worker_done` / escalation | 正常通知经 ACS；工作流动作通过宿主既有受权入口结算，仅存 receipt/handle 关联，不增 ACS Task 状态 |
| 自动 mailbox wake | 从 ACS 已有维护/接收链到 Host，停用同一身份的旧提醒回路 |
| remote / federation A2A | 走 ACS 到实际远端 Receiver；保留远端工作区与进程控制通道 |
| Agent 发起的终端定向消息 | 目标确为另一个 Agent 时经 ACS；人工终端操作/普通 shell stdin 不拦截 |
| UI 通信与通知 | 使用 ACS client service，不读旧消息表作为新消息来源 |
| 旧消息历史 | 只读标示为迁移前历史，或用明确导入工具导入；不重新投递 |

## 可信身份和地址解析

Session/terminal/run/dispatch handle 是宿主既有指针，不是 ACS 作者授权。集成从当前可信调用上下文解析 session → stable Slot / Client。旧命令中的 `--from` 不得覆盖真实作者。目标映射找不到时引导用户选择/连接真实 Agent；不自动冒名创建同名协作者。

映射优先存入现有 NativeLink 或 Host session metadata 的 `acs` 扩展字段。Project、Run、Worktree、Route 不做强制一对一转换。多工作区可属于一个 ACS 项目；多个 Run 可发生于同一 Route。人工在消息 UI 发信显示当前 Client；正常 Chat 中讲话仍是原生用户输入。

## 工作流一致性：最小适配，不重建协调协议

既有 worker_done 命令先经当前 Dispatch 权限校验。复用其现有 mutation receipt，记录 ACS 请求键与消息句柄以及“通知待完成/已提交”的事实，再推进原有任务结算或既有恢复流程。跨两个存储不是一个原子事务；不要假称全局原子完成。

发生中断时，用原 ACS key/operation 回查或按已证实无副作用的路径补齐；宿主使用原工作流操作 ID 防止重复结算。优先扩展原有 receipt 字段，不新增两阶段提交协调器、独立任务数据库或跨域 ledger。若旧接口要求先结算再通知，可保留顺序，但 pending notification 必须可恢复，不能因为消息通知失败回滚已经完成的代码工作。

普通消息完全不走这一段。提问的任何合法 reply 都是通信回复；只有明确的 gate-resolve 等工作流动作才解除 Gate，不能把“收到消息”当作“批准执行”。

## 队列与唤醒

ACS Outbox 负责尚未交给接收端的通信；Host 原生队列负责已接纳输入。用已有 native admission result 区分 staged/pending 与确实接纳；不把一般 `{ok:true}` 转为 model 已处理。

一次实际输入只由宿主队列执行。旧 Orca wake 与 ACS wake 不双开；原生用户的队列、暂停和 steer 能力保留。支持安全排队则接入；只支持 idle 的接收端在 ACS 延期，UI 不隐藏等待。收到 `message_only` 不启动模型。

## 切换及历史

开发中允许隔离的上游 baseline profile用于行为核对，但普通 Porpita 安装仅用 ACS 通信后端。不要交付默认 Orca、ACS 仅实验开关的产品。

旧 app data 默认不共用。用户主动导入时，对历史与设置做副本，不篡改原 Orca 数据，不把历史问题重新发送。工程兼容别名可存在，但不能成为悄悄写旧通信数据库的入口。
