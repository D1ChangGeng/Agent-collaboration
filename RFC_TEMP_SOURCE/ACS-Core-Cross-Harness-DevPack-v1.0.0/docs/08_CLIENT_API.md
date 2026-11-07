# 08｜客户端 HTTP API 与数据模型

规范文件：`contracts/openapi.yaml`、`contracts/models.schema.json`。这是目标新增 `/api/communication/v1` facade；复用现有 Domain/Project Service，不替换既有 MCP。除健康/版本外所有端点受认证，project 路径仅选择隔离范围、不授予权限。

## 对象

Actor：当前可信身份与实际授权动作；Contact：稳定地址、显示元数据、manager、授权可见 scope 与接收位置摘要；Conversation：Project 中两端地址的查询投影；Message：不可变原文、作者、to、reply_to、附件与提交顺序；DeliveryFacts：技术送达多维事实；Receiver：绑定/主机/原生 Session 引用和能力观察；Notice：系统通信故障，不是 Agent 回复；PersonalState：阅读/静音/归档/草稿，不改变公共历史；NativeLink：仅关联宿主 session 和 linkage，不复制其 transcript。

## 端点总览

| 用途 | 路径（前缀略） | 行为 |
|---|---|---|
| 握手/当前身份 | GET /meta、/profile | 协议版本、真实功能、授权身份；不准备接收端 |
| 项目/Route/联系人 | GET /projects、/projects/{p}/routes、/contacts | 复用现有可见性和分页 |
| 会话列表与详情 | GET /projects/{p}/conversations[/{id}] | 根据消息投影；没有强制 create 会话步骤 |
| 历史 | GET /projects/{p}/messages | peer/conversation/reply_root 可选，稳定分页 |
| 原文 | GET /projects/{p}/messages/{h} | byte offset/预算，原文与首回复独立续读 |
| 发送 | POST /projects/{p}/messages | Idempotency-Key 必需；作者服务器确定 |
| 等待/查询原操作 | POST /projects/{p}/waits；GET /operations/{id} | timeout 不是发送失败；无重复激活 |
| 单消息事实/技术尝试 | GET /messages/{h}/delivery | exact operation/绑定/证据；正文另查 |
| 状态/能力 | GET /projects/{p}/receivers[/{id}] | 多轴 observed/inferred/unknown |
| 恢复动作 | POST /projects/{p}/receivers/{id}/actions | 受权/版本条件/副作用判据；异步 receipt |
| 当前快照/实时 | GET /projects/{p}/snapshot、/events | consistent snapshot + replay SSE |
| 个人状态 | PUT /conversations/{id}/read-state、/preferences、/draft | 单调水位/CAS，不消费消息 |
| 系统通知 | GET /projects/{p}/notices；PUT /notices/{id}/seen | notice 独立 ACK，不代答 |
| 检索 | GET /projects/{p}/search | ACL + cursor + snippets/continuation |
| 附件 | POST /projects/{p}/attachments；PUT /attachments/{id}/content；POST /finalize；GET /content | 限额、校验、权限和生存期 |
| 原生关联 | GET /projects/{p}/native-links；PUT /native-links/{id} | exact scoped source reference，写需授权 |

完整 operationId、request/response/schema/错误见 OpenAPI。项目与团队配置继续走既有受权 MCP/管理服务；不在 HTTP v1 复制一套 configure lifecycle。集成 SDK 的管理调用 delegate 到该现有服务，并要求相同权限和结果映射。

## 写操作与响应

HTTP send 接受 `to, content, reply_to[], activation, response_mode, wait_timeout_seconds, deadline, attachment_refs[]`。旧 MCP 未扩展前不接纳 attachment_refs；HTTP 后端必须在同一通信服务中实现其受权扩展，并明确 bump catalog 的实际版本。不要在正文拼接外部附件权限来绕过扩展。

提交成功返回 201（重复键返回 200），包含 message、delivery facts、operation_ref、duplicate 和 wait outcome。sync 到时仍是已提交 response + timed_out，不返回 504 诱导重发。事务失败不创建消息；提交后观察失败必须返回/可恢复原 handle。

body budget 1..65536 字节；list limit 1..100，默认 50；reply_to 最大 32。新 HTTP content 最大 256 KiB UTF-8（部署允许调整，meta 必须公布）；旧 MCP 保持原上限/格式，不由新面收窄。附件单个默认 20 MiB、单条最多 8 个、总量默认 50 MiB，所有限制先在 meta 暴露后在提交前执行。附件阈值是本包建议配置，不是上游能力事实。

## 只读语义

list/read/search/snapshot/SSE 都不 mark_read，不启动/恢复 Session。read-state 是显式个人操作，前进 through_message_handle 必须属于当前 conversation 的可见记录。个人 archive 只隐藏列表、不撤销通信或删除对端历史；新收到消息可按个人策略重新浮现。

## 错误

所有失败返回 code/message/retryable/effect_state/operation_ref?/details。effect_state 为 none/committed/native_possible/unknown；若已有提交不能返回效果为 none。429 带 Retry-After 和明确没提交，503 未提交与“已提交但观察不可用”区分。错误词汇见 error-codes.json。详细恢复建议必须在权限内，不泄露另一个 namespace 的配置。

## 对话/关系的范围

本轮 conversation 限直接双方，群组不是强制新增组织。通过一条回复可关联同一对端多请求；线程投影以显式关系为准，不能用 UI thread ID 取代回复授权。未来多方群组需要单独契约，当前 unsupported，不阻塞对 Orca 当前一对一 Chat 的完整数据接入。

## 幂等与版本前提的顺序

写请求先验证当前读取/操作权限，再检查同幂等键已提交 receipt 与 canonical request hash；相同请求重放返回原 outcome，不因后续 revision 前进而执行第二次。仅新请求才按 If-Match/expected revision 争用。已撤销主体不能借旧 key 重新读取私密结果。原生副作用仍须手动对准原 operation/去重域，不因 HTTP 重放执行新的 Native 调用。

## 首条消息之前的草稿和空视图

`GET /projects/{p}/conversations/resolve?with=<address>` 在验证联系人权限后返回稳定的双方 conversation view；没有历史时 last_message=null、revision=0。该只读解析不得启动 Session，也不要求持久创建独立领域会话。ID 由现有稳定地址对和 namespace 生成/解析，碰撞、租户隔离与重新配置保持一致；不能用当前显示名或 Native Session ID。

个人 draft 可键到这个已授权的稳定 view ref；不存在实体行时返回 revision 0，首次写使用 `If-Match: "0"`。首条消息提交以同一 ref 物化可重建消息投影。这样草稿可先同步，而普通发送仍无 create conversation 前置。`/conversations/resolve` 路由必须早于动态 `{conversation_id}` 注册。

NativeLink 的 provider/session 字符串不是授权证明。写绑定时 Core/集成层须向真实受信宿主验证 session 所有权、scope 和当前 generation；不能只因 HTTP 调用者是 manager 就读取或控制宿主全部会话。
