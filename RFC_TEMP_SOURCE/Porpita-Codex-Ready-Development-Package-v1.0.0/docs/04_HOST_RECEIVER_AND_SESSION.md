# 04｜真实宿主接收与原生会话接线

## 已有与缺口

ACS 已有 `ExistingOrcaReceiverBackend` / `OrcaReceiverRouter`、`TrustedOrcaReceiverPort` 和四项接收契约。其 Host 回调在既有测试中由替身提供；本轮把回调接入真实 Porpita Host。不得重新写一套 Python Receiver 或仅继续完善 mock。

Orca 当前 handover 接入点：
`src/main/native-chat/agent-session-wire/delivery/structured-agent-session-input-handover.ts`。
已核查其在 session serialization 中进行准备与真实 enqueue。`agent-session-mutation-envelope.ts` 的普通 writes 忽略 `expectedRuntimeFence`；这说明普通 RPC 回包不能直接当作 ACS 原操作接纳证据，不代表要推翻上游整个生命周期。

## 一条消息的具体实现顺序

1. Native Agent A 使用自己的 ACS MCP 绑定执行 send_message。Core 持久提交 Message、原 operation 与 Outbox。
2. 根据 B 的稳定 Slot 与当前 Receiver 选择实际 Host。Core/Receiver 复用已有签名 prepare/readiness/dispatch 路由。
3. ACS Python backend 用已有 verifier、prepared ledger 和原 dispatch 解析输入；不要调用会顺带触发 ACS Driver 的 `_admit` 作为“纯验证”。
4. 到真实 Host：解析当前 NativeSessionRef/owner，调用已有串行 input handover。由 Host 执行最小的当前会话和输入条件检查，复用队列/审批阻塞逻辑。
5. 已真正接纳的 input/turn 引用与结果回到原 Receiver receipt。仅写入 journal/pending 时仍是待交接，不伪装已接纳。
6. Native Chat 显示来源为协作者的输入，并正常流式展示工具/模型行为。B 通过自己的 ACS send_message 带 reply_to 回信；普通 assistant final 不自动生成回复。
7. 原消息查询可使用 SourceLink 定位当时真实 input。当前 Session 后来改变，也不改写历史来源。

## Python 与 TypeScript 进程边界

不要把两个语言接口都强制塞进同一进程。首选复用现有 ReceiverHTTPServer/Router：Python 保持 ACS 验证与原回执，Host 的原生 observe/admit/reconcile 通过**私有、受限的本机桥**调用。优先使用宿主现有 typed IPC；确有必要时使用用户私有 pipe/loopback IPC，协议只搬运现有已验证 DTO 和结果，不新增公网 verifier API。

Host 内最终检查必须在原生 serialization 内，与 enqueue 同一控制路径执行。桥的 timeout 不可将已经 enqueue 的输入重新表示成无副作用。Python 与 JS 双重 wrapper 没有增加保证时，可删去重复转换或重复校验；保留一个实际验证入口与一个真实原生 handoff 即可。

`TrustedOrcaReceiverPort` 是可复用实现，不是要求层层套用的仪式。采用不同的薄接线时，记录它如何复用原 verifier/ledger 与 Host queue；不要再维护第三个 operation store。

## 每个会话的注册

Agent 首次启动/已有会话加入协作时，宿主完成稳定 ACS 地址与 NativeLink/Receiver 关联，生成受信 MCP 接入配置，并将实际角色/联系人/回信规则提供给模型。不让用户填写 ID。绑定失败不影响普通本地 Chat，但不能显示“协作已连接”。

同一 Native Session 的进程/输入仍由 Porpita Host 管理。ACS独立 Driver 只用于独立 Harness，不控制已由 Host 管理的同一会话。

## 两个必须正常工作的使用时机

- 空闲会话：发信后正常接纳，模型执行并显式回信。
- 忙碌会话：优先复用上游 queue，不强制暂停/steer；遇到等待审批按原生行为等待或在可证明安全的队列中排入。UI 保留自己的草稿和待处理问题。

一次断开/重开也需能接续已有消息。无需验证全部不可能枚举的故障窗口；至少检查重复点击/网络结果未知不形成第二次实际输入，以及 Session 重新绑定后不向错人发信。

## Remote / WSL

Receiver 必须运行在 Native Session 实际所属 Host，复用已有远端连接与 ACS Node/Receiver。WSL/SSH 若上游仅支持 terminal-backed Chat 就保持该形式。不要通过 renderer 的终端文本输入绕过实际远端接收。远端可读附件也必须在目标 Host 材料化。

## 首代验收出口

Codex 与 OpenCode 在安装后的 Porpita 中完成真实来回消息；工具调用/审批仍在原界面；关闭重开后通信历史及当前原生会话可继续。没有实际 Host 接纳，不能以 `host_extension_required` 作为已完成该必交功能的正常结果。
