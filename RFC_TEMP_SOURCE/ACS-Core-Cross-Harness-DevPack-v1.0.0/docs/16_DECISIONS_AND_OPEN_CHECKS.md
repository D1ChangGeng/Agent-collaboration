# 16｜实施时核对项，不重新打开产品方向

## 已确定，不再做选型研究

保留 ACS 的通信/组织语义、Python/PostgreSQL/现有 receiver 主链；任务编排独立；原生执行与 Chat 数据归宿主；插件优先、UI 不在本轮；真实未知不伪装成功；保留 Core 独立运行。

## Codex 自主核对并落实

| 核对项 | 默认实施决策 | 证据/输出 |
|---|---|---|
| 当前 repo 比参考提交更新 | 使用现有分支增量开发，不回退 | baseline diff 与兼容影响 |
| 旧 operation 表能否承载新 receipt | 优先扩展，避免重复 ledger | migration rationale |
| Provider 是否有原生 idempotency/query | probe+真实协议；不支持则 unknown 不重放 | capability evidence |
| Hook/PTY 来源能否认证 | 无认证仅 inferred，不作安全准入唯一凭据 | adapter-negative tests |
| Orca 是否公开原生 transcript/input port | 用固定 revision 真实目录核对；没有则 host gap | symbol/API/最小 port 合同 |
| draft/approval native 操作 | 仍由原宿主处理，不进入 ACS message lifecycle | delegation tests |
| 空 Conversation 的展示 | 由联系人启动临时 view，首消息时生成投影；不要求新 domain session | client tests |
| 历史未标记作者 | unknown/archived，只读，不猜 | backfill evidence |
| 全量 UI 字段超出已读范围 | 在 WP08 阅读真实 Renderer 依赖并补 mapping | 完整 ui-readiness 清单 |

“待核对”不是留给用户的设计问题，也不是执行暂停条件。Codex 可按既定原则处理；仅权限、生产/外发授权和无法取得的外部凭据才形成执行阻塞。

## 明确禁止绕路

不能增加 WorkItem 改名后的业务对象；不能给所有 agent 强制工单/心跳；不能让普通通信先建立 Run；不能把用户输入自动当管理授权；不能因插件 API 少就直接改内部 DB；不能只做 Mock server 或接口文件便宣称功能实现。
