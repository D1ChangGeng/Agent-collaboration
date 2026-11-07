# 17｜集成审查清单

最终审查按数据流而不是文件数量进行。

**发送**：真实 caller → live permission → dedup → 原包/索引/Outbox/event 同 commit → 带真实 effect_state receipt。

**接收**：稳定地址 → 唯一合法 binding → 当前 capability/observation → durable operation → receiver fence → native admission → evidence / unknown。

**回复**：对端独立 send → 同对端 reply_to 校验 → 原文和关联保存 → 活动 wait / Inbox → 无重复唤醒。

**恢复**：原 operation 和原去重域 → 查询证据 → 明确未接纳才安全重试；rebind 不擦除 unknown，旧代次无权新执行。

**客户端**：权限筛选 snapshot → 同边界 cursor → 事件重复/断档/撤销处理 → 显式 read state → native 双源来源清晰 → 不自动消费或造回复。

**部署**：显式 schema adoption → 数据完整性/备份恢复 → 旧客户端兼容 → 维护器持续 → capability 支持矩阵 → 没有未经授权生产切换。

任何一项只靠注释说明、mock 标绿或 self-report，没有相应边界测试，则退回工作包修复。审查结果要记录真实证据层次，不把静态阅读称为运行验证。
