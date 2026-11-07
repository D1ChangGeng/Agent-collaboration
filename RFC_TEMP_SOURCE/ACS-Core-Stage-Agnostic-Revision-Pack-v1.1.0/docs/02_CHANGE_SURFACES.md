# 02｜改造面与“能力新增/保障/产品”分界

改造条目以 `contracts/change-items.json` 为机器清单；每项具有 `tier`、`kind`、`minimum_behavior`、`reuse_first`、`acceptance`，并通过 `old_work_packages` 和 `old_requirements` 回指 v1.0.0。

## 本轮最可能产生实质覆盖收益的 6 类能力

| 面 | 新可用行为 | 既有 ACS 基础 | 先核实什么 | 不得重复实现 |
|---|---|---|---|---|
| Adapter 的能力/证据发现 | 从“知道是 Codex”到“知道它在本机当前配置中可安全使用哪些输入能力” | Codex/OpenCode Driver, `list_harnesses` | 原生接口/版本/OS/授权模式与实际证据 | 第二套 Harness 信息权威 |
| Native 输入准入 | 忙时安全延迟/有证据的原生排队，审批/草稿不受打断 | Native Receiver, busy 退避 | 真实 Provider 队列与审批状态语义 | 通用的强制键入/steer |
| Operation reconcile | ACK 丢失时查询同一原生操作是否已接纳，安全恢复 | Outbox/operation/Node Journal | 现有账本字段与日志对账能力 | 第二套独立操作账本 |
| Session continuity | 已受信的 Session 重连/恢复或明确新绑定，消息身份与旧回信不丢 | Slot/Endpoint/Session 分离 | 恢复是否原生可用、是否有授权 | 未经批准的新 Session/伪造工作记忆 |
| 跨主机能力协商 | 混合版本和网络故障时有证据地路由/暂缓 | Node/Receiver/Tunnel | 当前握手和审计链 | 第二套 Relay 协议，除非真实缺口 |
| 外部宿主 Receiver port | 在 Orca 已拥有的 Native Session 中合法接收 ACS 消息 | 独立 Receiver 主链 | 现有公开插件是否有安全 input host action | 与 Orca 同时争抢输入 owner |

## 正确性保障：有必要，但多数是“核验/补洞”

G01 可信 sender 与 Scope：已有基础，持续 regression。G02 同消息/回复权威：已有基础，不能因 HTTP/Orca 接入破坏。G03 Native ACK / 显式 reply 分离：已有，任何新 view 不得缩短。G04 接收绑定代次和已发生副作用 unknown：新增 native path 时重点加固。G05 不消费历史、稳定分页、UTF-8：旧 MCP 必须保持，P1 查询复用。G06 恢复与并发限制：已有有界调度及通知机制，先证明需要拓展。G07 Host single-writer：仅在同一 Native Session 双控制面情况下特别重要。

## 客户端“必要通信功能”与“可选个人体验”

P1 必须具备当前身份、可见联系人/项目、只读 Conversation、消息历史/发送/关联、技术状态、系统通知、快照+可重放事件、当前接收者能力、明确恢复路径、NativeLink/宿主 port/功能降级。P1 可以无 UI；独立使用 ACS 仍通过 MCP，不依赖 Orca。

P2 的二进制附件、搜索、阅读水位、草稿多端 CAS、静音/归档对核心发送链路没有必要性；若已有实现则保留其安全/授权不变量，不退化为未经授权访问。

## 一个典型端到端案例

A 通过现有 `send_message` 向长期 B 地址发信；Authority 原子写入原文、回复关系与 Outbox；接收侧选择唯一获授权 Endpoint；Adapter 声明的能力和新鲜观察决定是 handoff、排入原生队列、留 ACS Inbox，还是阻塞；接收端再次重验身份、binding/Session 版本；Native 可能接纳结果持久记录；未知结果只对同 operation 对账；B 以自己身份主动 `reply_to` A。Orca UI（如果安装）只读取 ACS 通信事实并将 Native 执行内容交给原生 Host 展示。
