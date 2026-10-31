# 正式 OpenCode Receiver：真实 Session 与双模型 Native 闭环

接续 `a8bf4c3c1dbbb6fc4c0735ca863a4bd9e221211b`，分支 `codex/core-cleanup`。
完整目标仍 active。没有 Push、部署、生产清理、正式 checkout 或服务切换。

## 实际代码

- 新增 `runtime_deployment.receiver_opencode:callbacks`，使用真实
  OpenCodeNativeDriver、NodeJournal、ReceiverNativeDeliveryBridge 和现有签名
  Receiver 接口。只接纳 Owner 配置，Shared 必须有单独资格，不能自动降级。
- `receiver_authority.py` 抽出 Codex 已有的实际 Node 观察者绑定、已提交消息
  发送者重新鉴权、生命周期绑定与旧任务包拒绝。Codex/OpenCode 复用这些检查，
  不复制另一套授权真相。关闭时即使生命周期授权已撤回，也释放传输与自有监管。
- OpenCode Native 的 agent/provider/model 可以从选定环境继承；显式 provider
  和 model 必须成对。Session metadata、目录、消息 ID/文本及显式选择仍读回
  验证，restricted 参考配置继续要求固定选择和原有保护。
- 真实 Factory 验证发现 Owner 关闭路径错误调用不存在的 LoopbackHttp.close。
  现与既有停止/诊断线程收拢路径统一，保留进程组或进程树的实际停止证明。
- 新增 `docs/runtime/OPENCODE-RECEIVER.md`，说明配置、选择继承、可观察事实及
  Owner Linux 进程组边界。没有终态 Collector 或后台 SSE 执行观察。

## 实际验证

| 范围 | 结果 | 材料 |
|---|---|---|
| 工厂、共享鉴权、Driver、HTTP/Adapter/读回竞态 | 105 passed / 8 skipped | `final-source.xml`；合成 Peer 明确属于组件证据 |
| 正式 OpenCode Factory 零模型准备 | 1 passed，20.98 秒 | `actual-factory.xml`、`session/` |
| 正式 OpenCode Factory：脚本 A、真实模型 B | 1 passed，45.95 秒 | `actual-model.xml`、`single-model/` |
| 独立 Codex A 与 OpenCode B 真模型闭环 | 1 passed，152.25 秒 | `dual-model.xml`、`dual-model/` |
| 共用鉴权后既有 Windows Codex Factory 真模型回归 | 1 passed，85.44 秒 | `codex-regression-model.xml` |
| 1302-1 真实 OpenCode Driver 零模型生命周期 | Session 创建/读回、停止证明通过 | `remote-driver/facts.json` |
| 当前 wheel 实际安装与公开工具 | 106 文件匹配、46 表、2 消息/1 回复 | `installed-candidate.json`；脚本、无模型 |

本机 OpenCode 1.18.34 来自 1302-1 的程序文件，只取回程序，不复制其配置或
凭据。实际 Linux/WSL Factory 以真实 PostgreSQL Node/Runtime 登记取得观察者
身份，创建真实 Session；configure_team 返回同一 Session，未发模型请求。
停止后自有进程组为空；此范围不是 subtree containment 或 Shared/Systemd 资格。

双模型测试中，A 是实际 Codex CLI，B 是独立 OpenCode 模型 Session，双方都是
普通 engineer 身份，经各自正常 MCP 工具收发。A 的环境剔除了 B 的初始答案、
OpenCode 配置和 MCP 凭据。评测器仅观察 A 已提交的 operation 并驱动真实
dispatcher；没有把请求正文或回复句柄转交 B，没有代写回复或投影终态。
实际只有一次 prompt_async、2 条消息、1 条主动关联回复，Work 表不存在。
模型选择从隔离 OpenCode 配置继承，Collector/SSE 均为 false。
耗时包含模型/Provider 和网络，不是 ACS 传输延迟。

新 wheel SHA256：`6a1ed49128ce04854119e021f5ffac9aa6da83d7c774885240b0cb543f76b868`。
源码和安装的 106 个 Python/SQL 文件逐字节匹配，旧 DDL/测试夹具未打包。
软件版本仍为已有的 0.1.0，未将文档包版本当成软件发布版本。

## 保留失败、授权与限制

`shared-authority-first.xml` 保留测试替身缺失 Domain access_mode 的首次失败；
替身补齐真实接口，未弱化实际身份检查。`actual-factory-close-failure.xml` 保存
真实关闭缺陷，修复后原流程全部通过。`dual-model-approval-failure.xml` 保存
测试 Codex 客户端取消 MCP 写调用；隔离配置补齐预先授权的 send_message 后
真实双模型通过，未绕过服务端授权或删改关联断言。

第一次远端源码上传曾被自动审批拒绝，未绕过。先在本机 WSL 完成不涉及源码
外发的验证；用户随后明确授权 Runtime .py/.sql 副本传入 1302-1 独立 /tmp，
才进行远端正式 Driver 探针。该探针零模型，不更换正式环境。取回材料时一次
临时路径错误已按探针返回的实际 root 修正，没有重新启动或复制 Native 操作。

本阶段双模型自动激活在同一机器的 Linux/WSL Runtime 中验证；1302-1 只验证
真实 Driver 生命周期，没有证明物理跨机器签名 Receiver 的模型自动激活。
Windows Job 既有 Codex 回归通过；Shared OpenCode、Linux 受限配置、旧进程
隔离/故障替换、生产迁移与发布仍需对应证据和授权，完整目标未称完成。
