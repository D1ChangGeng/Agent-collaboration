# 12｜API 与客户端能力接入矩阵

## P1 必交的 ACS 通信服务

| OperationId | Method | 目标路径 |
|---|---|---|
| `getMeta` | GET | `/meta` |
| `getProfile` | GET | `/profile` |
| `listProjects` | GET | `/projects` |
| `listRoutes` | GET | `/projects/{project_id}/routes` |
| `listContacts` | GET | `/projects/{project_id}/contacts` |
| `listConversations` | GET | `/projects/{project_id}/conversations` |
| `getConversation` | GET | `/projects/{project_id}/conversations/{conversation_id}` |
| `listMessages` | GET | `/projects/{project_id}/messages` |
| `sendMessage` | POST | `/projects/{project_id}/messages` |
| `readMessage` | GET | `/projects/{project_id}/messages/{message_handle}` |
| `getDelivery` | GET | `/projects/{project_id}/messages/{message_handle}/delivery` |
| `waitForMessages` | POST | `/projects/{project_id}/waits` |
| `getOperation` | GET | `/projects/{project_id}/operations/{operation_id}` |
| `listReceivers` | GET | `/projects/{project_id}/receivers` |
| `getReceiver` | GET | `/projects/{project_id}/receivers/{receiver_id}` |
| `recoverReceiver` | POST | `/projects/{project_id}/receivers/{receiver_id}/actions` |
| `getSnapshot` | GET | `/projects/{project_id}/snapshot` |
| `subscribeEvents` | GET | `/projects/{project_id}/events` |
| `listNotices` | GET | `/projects/{project_id}/notices` |
| `listNativeLinks` | GET | `/projects/{project_id}/native-links` |
| `bindNativeLink` | PUT | `/projects/{project_id}/native-links/{link_id}` |
| `resolveConversation` | GET | `/projects/{project_id}/conversations/resolve` |

## P2 可选、不得作为 P1 阻塞

| OperationId | Method | 目标路径 |
|---|---|---|
| `getReadState` | GET | `/projects/{project_id}/conversations/{conversation_id}/read-state` |
| `markConversationRead` | PUT | `/projects/{project_id}/conversations/{conversation_id}/read-state` |
| `getPreferences` | GET | `/projects/{project_id}/conversations/{conversation_id}/preferences` |
| `setConversationPreferences` | PUT | `/projects/{project_id}/conversations/{conversation_id}/preferences` |
| `getDraft` | GET | `/projects/{project_id}/conversations/{conversation_id}/draft` |
| `saveDraft` | PUT | `/projects/{project_id}/conversations/{conversation_id}/draft` |
| `markNoticeSeen` | PUT | `/projects/{project_id}/notices/{notice_handle}/seen` |
| `searchMessages` | GET | `/projects/{project_id}/search` |
| `reserveAttachment` | POST | `/projects/{project_id}/attachments` |
| `getAttachment` | GET | `/projects/{project_id}/attachments/{attachment_id}` |
| `uploadAttachment` | PUT | `/projects/{project_id}/attachments/{attachment_id}/content` |
| `downloadAttachment` | GET | `/projects/{project_id}/attachments/{attachment_id}/content` |
| `finalizeAttachment` | POST | `/projects/{project_id}/attachments/{attachment_id}/finalize` |

P1 OpenAPI 文件：`contracts/openapi-p1.yaml`；P1 DTO：`contracts/models-p1.schema.json`。未实现 P2 不得在运行中的 meta 宣称其可用；已经实现的 P2 不删除，仍受旧客户兼容要求。

## 30 项 UI 来源清单

| UI | 级别 | 数据权威 | 最小集成方式 |
|---|---|---|
| UI01 | P1 | ACS | 可信身份与权限动作 · acs_communication_service |
| UI02 | P1 | ACS | 项目与 Route 导航 · acs_communication_service |
| UI03 | P1 | ACS | 联系人/收件地址 · acs_communication_service |
| UI04 | P1 | ACS | 通信会话列表/摘要 · acs_communication_service |
| UI05 | P1 | ACS | 历史分页/定位/长消息 · acs_communication_service |
| UI06 | P1 | ACS | 显式关联回复/线程 · acs_communication_service |
| UI07 | P1 | ACS | 普通发送/等待/不重复 · acs_communication_service |
| UI08 | P2 | ACS | 个人未读/已读/静音/归档 · acs_communication_service |
| UI09 | P2 | ACS | 草稿与多设备恢复 · acs_communication_service |
| UI10 | P2 | ACS | 消息搜索与摘要 · acs_communication_service |
| UI11 | P1 | ACS | 原始送达状态与技术尝试 · acs_communication_service |
| UI12 | P1 | ACS | 能力/运行状态与证据 · acs_communication_service |
| UI13 | P1 | ACS | 故障诊断/恢复操作 · acs_communication_service |
| UI14 | P1 | ACS | 通知与个人 seen · p1_notice_list_p2_personal_seen |
| UI15 | P2 | ACS | 附件/图片上传下载 · acs_communication_service |
| UI16 | P1 | ACS | 实时更新/重连/快照 · acs_communication_service |
| UI17 | P1 | ACS+host | Native Session 关联 · acs_and_host_linkage_contract |
| UI18 | P1 | host | Native transcript/消息流 · host_delegation_contract |
| UI19 | P1 | host | 工具调用/结果/进度/长输出 · host_delegation_contract |
| UI20 | P1 | host | 原生 Diff 卡/文件打开 · host_delegation_contract |
| UI21 | P1 | host | 子 Agent / 后台任务行 · host_delegation_contract |
| UI22 | P1 | host | 原生问题/审批交互 · host_delegation_contract |
| UI23 | P1 | host | 原生发送/stop/resume/排队编辑取消 · host_delegation_contract |
| UI24 | P1 | host | 模型/effort/usage/上下文展示 · host_delegation_contract |
| UI25 | P1 | host | Native Session 历史/clear/compact · host_delegation_contract |
| UI26 | P1 | host | 工作区/Terminal/Git/编辑器定位 · host_delegation_contract |
| UI27 | P1 | ACS+host | Native 来源标识与去重链接 · acs_and_host_linkage_contract |
| UI28 | P1 | integration | 插件宿主能力与降级 · acs_communication_service |
| UI29 | P1 | ACS+host | 权限变化与缓存失效 · acs_and_host_linkage_contract |
| UI30 | P1 | ACS | UI 关闭后连续通信 · p0_core_independent_p1_client_projection |

**Host 来源能力只要求委托与不可用降级合同，不要求 ACS 复制工具/Diff/审批/模型/Worktree，更不等于真实 Orca Host 已资格化。**
