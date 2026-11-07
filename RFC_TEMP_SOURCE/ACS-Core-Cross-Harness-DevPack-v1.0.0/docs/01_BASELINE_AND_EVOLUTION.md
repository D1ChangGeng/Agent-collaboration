# 01｜真实基线与增量演进

## 来源与事实

来源索引见 `sources/SOURCE_INDEX.md`。A01 确认现有 pyproject 版本 2.3.1、Python >=3.12、runtime/runtime_deployment、psycopg/Temporal/FastAPI/MCP 依赖。A02 确认通信契约；A03 为支持范围记录，须继续区分真实模型、受控 Adapter、安装验证和生产资格。不得将旧 UPGRADE-CONTRACT 中已退休任务架构重新作为当前设计。

当前基线已明确：稳定身份；可信 Client 无固定 Slot/Native Session；`send_message` 默认 invoke+async；显式同对端 `reply_to`；读取不消费；UTF-8 续读；原键防重；四项默认运输并发与 per-Slot Native admission fence；未知 Native 不盲重；manager 系统通知与私信/回复分开。上述是**保留项**，不是本轮新发明。[A02]

## 源码落点（执行时确认符号/调用链，不能按文件名机械复制）

| 现有文件/域 | 保留 | 增强 |
|---|---|---|
| runtime/communication.py、communication_tools.py | natural send/read/wait/contacts 语义 | 复用领域调用，追加客户端读模型，不制造第二 send 实现 |
| communication_dispatch.py、native_delivery.py | Outbox、请求键、Native fence | 分阶段 Native receipt、能力快照、恢复判据、唤醒合并 |
| communication_management.py、communication_permissions.py、agent_organization.py | Client/Root/Route、部分合并、版本和可信绑定 | 接收绑定代次/能力选择、客户端可见动作；不增加管理层 |
| runtime/codex_driver.py、opencode_driver.py | 已验证原生输入/Session 接入 | 同一 Adapter 契约、观察证据、原生操作查询与恢复 |
| runtime_deployment/receiver*.py | Node 授权、接收端签名和主机校验 | transport reconnect、对端能力协商、局部日志核对 |
| communication_core_schema.sql、communication_schema.sql、project_schema.sql | 现有主表/索引/作者/历史 | 显式 additive migration，客户端视图/事件/操作证据 |
| project_mcp_server.py / project_http / entry 模块 | 默认入口维护、认证/工具发现 | HTTP facade、授权一致的订阅、服务退出/重连 |
| filesystem_gateway.py、project_source.py | 文件和 Source 独立权限 | 引用/附件读取复用，不因消息包含路径自动导出 |
| runtime_tests/、integration_evidence/ | 既有真实范围和失败记录 | 新契约、并发/故障、安装后回归 |

以上未在本包逐行读取的路径是 implementation_check；执行时以 git ls-files/rg 和调用链核对。已确认文件及行范围在 source-lock 中单列。

## 禁止的“重构捷径”

不要迁移到另一语言重写 Core，不替换 PostgreSQL Authority，不为照搬 Orca 添加 SQLite 消息主库，不新建 competing task coordinator，不在 Adapter 内复制权限决策。Node 本地 journal 是副作用证据，不是新的业务权威。

不要为 UI 删掉历史复杂状态。先复用现有数据与既有合法的 phase，再在 read-model 归一化。不要把 Client 的 null Slot 补成假 Root，不把旧 Session ID 当长期联系人。

## 新增的最小逻辑域

1. `communication capabilities/observations`：接收端可用能力、证据与时效。
2. `native input operations`：原生输入接纳前后的可核验操作日志；若旧表已足够，扩展而不是重复。
3. `client read models/event journal`：会话投影、个人未读、订阅与检索。
4. `integration bindings`：ACS 地址↔宿主原生 Session 引用，非原生 transcript 主库。
5. `attachments/drafts`：明确权限的通信附件和个人未发送草稿。

每个新增表提交“为何不能复用现有表”的简短说明。数据模型数量不是目标，语义完整性与单一权威才是目标。
