# 15｜运行、诊断、资源与支持声明

## 可观察性

每条技术尝试提供 trace_id/message_handle/operation_id/receiver/binding epoch/adapter build、状态改变及 reason/evidence refs。默认不记录私信正文/Token/原生推理。普通用户只看其有权消息的诊断；管理员技术视图也必须脱敏。

指标：accepted messages、outbox depth/age、deferred by reason、native unknown count/age、reconcile outcomes、duplicate suppression、receiver observation freshness、wait lease reclaim、event replay/resync、consumer buffer overflow、attachment errors、auth denials。默认 labels 不含消息 ID/用户名/正文；高基数详情在受控 trace，不在 metrics labels。

## 健康与能力

health 表示进程/数据库/维护器状况，不表示所有 Harness 就绪；readiness 区分 API 可用、存储可写、维护器运行、特定 receiver 功能。meta 暴露当前 schema/feature/限额，不返回 credentials。receiver unavailable 不应使无 Native 的 message_only 不可用。

## 容量与背压

保留现有默认最多四运输并发，按 slot 串行 admission。新增按 tenant/receiver 公平队列；明确 backlog/配额拒绝发生在接受前还是 Native 延期。未知 operation 占用风险不得靠无限增大队列隐藏。连接池、订阅、附件 staging 与 stdout/log 都有限额。

## 运维操作

只读 inspect/reconcile 优先。恢复 receiver/绑定更改需明确授权和期望版本。不能由健康检查自动 prepare/spawn。旧安装的 updater/服务生命周期照现有机制扩展，runtime host 仍为已有支持范围，不因 UI 希望 Windows 就宣称 Core Windows 原生已支持。

## 支持报告

`handoff/qualification-matrix.json` 每行记录 harness/version/os/surface/transport/auth-mode/capability/verification evidence。unsupported 与 unverified 分开：前者有明确不支持依据，后者没有足够证据。Orca 源码包含实现不能替代已安装 profile 资格。部署/公开发行不在默认授权内。
