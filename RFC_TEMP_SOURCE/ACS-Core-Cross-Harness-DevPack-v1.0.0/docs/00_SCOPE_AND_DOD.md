# 00｜范围、固定决定与完成定义

## 目标

在保留当前 ACS 通信 Core 的基础上，实现跨 Harness 的稳定寻址、可信消息、能力感知输入、状态证据、持久投递、防重复 Native 激活、唤醒/恢复、跨主机接入及完整客户端数据服务。普通 Agent 使用统一消息语义，不需要判断目标 Harness 的输入协议或 Session 状态。

文中 MUST 为强制，SHOULD 为默认实现方向，MAY 为非阻塞扩展。机器接口是**目标新增契约**，不是当前已存在 API。所有包内建议版本号是规范版本，产品版本由执行时兼容审查决定。

## 固定架构决定

| ADR | 决定 |
|---|---|
| ADR-01 | 保留唯一 ACS Authority 与现有 Message/Inbox/Outbox 主链；不建立第二消息权威 |
| ADR-02 | 稳定 Client/Slot 与可替换 Native Session 分离；保留既有三级管理组织 |
| ADR-03 | 普通消息无任务前置；不引入业务 Work/Review/Task/Dispatch 状态 |
| ADR-04 | 投递、消费证据、显式回复和业务完成互不替代 |
| ADR-05 | Adapter 以能力和证据驱动；unknown/unsupported 为可见的一等结果 |
| ADR-06 | 所有 Native 副作用有持久操作标识、接收代次和不确定窗口处理 |
| ADR-07 | UI 数据走读模型/事件；完整原生 Chat 由 Orca/Harness 保持权威 |
| ADR-08 | 插件优先；公开扩展缺口以宿主接口描述，不假称已可替换 Orca 通信引擎 |
| ADR-09 | 增量迁移；旧消息、作者、关联和 request key 不重写；旧 MCP 行为回归 |
| ADR-10 | 本轮只有工程开发和工程验证，无比较/研究型实验、无 UI 设计或移植 |

## 必交范围

(1) Codex/OpenCode 现有接收器契约升级；(2) generic Adapter SDK 和 Orca-owned receiver integration seam；(3) 输入/恢复正确性；(4) 客户端通信 API、订阅、检索、附件、草稿与个人阅读状态；(5) 原生会话绑定与组合视图接口；(6) 宿主接入能力清单及无 UI 客户端验证；(7) 迁移、回滚、原始测试证据和运维说明。

无需为全部市面 Harness 各写一个 Driver。新增 Harness 可通过标准 Adapter 或已经接入的 Orca Session Provider 复用能力，只有验证过的组合可宣称支持。禁止用“大规模全平台支持”替代明确资格矩阵。

## 完成定义（全部适用条目闭环）

D1：旧 Client/Root/Route/ordinary Agent 的管理、通信、历史、身份、授权、默认值及大正文行为不回归。
D2：独立 ACS，不安装 Orca，仍可完成已支持 Codex/OpenCode 收发、显式关联回复和恢复。
D3：未知 Native 结果不被重发；旧代次不能提交新副作用；busy/审批/用户草稿场景不会被消息输入覆盖。
D4：HTTP 查询与实时事件在权限、并发、分页、断线和历史恢复上有自动化契约测试。
D5：UI 清单每项均有 authority、数据来源、操作/事件、capability、降级及测试；没有未定义数据洞。
D6：至少一个真实 ACS + 原生接收链、一个真实事件断线重连链、一个旧客户端兼容链通过工程集成。接入真实 Orca 宿主的资格单列，不可被 synthetic test 替代。
D7：数据库显式迁移与恢复演练完成；无破坏性自动升级；运行时持续维护不依赖 UI 开着。
D8：所有 R/WP/T 可追踪；有失败与修复记录；支持范围外明确 unknown/unsupported。

## 两类就绪必须分别签署

**Core/UI contract-ready**：ACS 全量通信服务、事件、集成接口、头部无界面消费者与契约测试实现完毕，原生非通信能力有明确 delegation，无悬空业务契约。
**Orca host-qualified**：在指定 Orca revision/插件 API/主机/Harness 上实际对接通过。若宿主公开 API 不足，应报 `host_extension_required`，Core 可单独完成，不能声称完整原生插件已上线。此区分不是缩小范围：所有后端和集成边界必须实现、可测；只有宿主实际改造/UI 开发不在本轮。
