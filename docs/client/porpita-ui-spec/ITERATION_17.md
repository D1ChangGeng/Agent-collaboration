# 第十七轮 · 查历史后回到原工作位置

从会话目录点「搜索历史会话」，Vault 接收当前查询并聚焦其输入。保留 Vault 的来源、结果、权限与恢复规则。目录的位置与分组留在原视图。Vault 的「跳转到原 Pane」从已知的本机结构化会话优先进入现有 Workspace，继续使用先前的 Composer。 [现有 Vault 查阅与回源](ITERATION_04.md) · [搜索转交](ITERATION_06.md)

| 条件 | 回放终点与后续边界 |
| --- | --- |
| 目录有查询 | 仅转交去掉首尾空白后的查询文字。Vault 使用既有请求处理与范围，历史输入取得焦点。首次索引准备中时，沿用右栏的重试动作，保持原查询。 |
| 可信历史已对应打开的本机 Chat，且引用在打开的 Workspace | 从 Dock 的原位动作进入原 Workspace 和 Pane，使用原会话与草稿，结果直接由现有焦点请求衔接。 |
| 历史对应普通工作树、终端或其他 Host | 使用 Vault 既有定位、来源校验和回退动作。可恢复的历史继续通过显式恢复命令打开。 |
| 从 Workspace 返回工作树 | 会话目录显示上次查询、筛选、分组。Vault 的扫描结果继续由自身刷新与权限裁定。 |

重用 `showAiVaultSearch`、`use-ai-vault-search-focus-request.ts`、`ai-vault-original-pane-actions.ts` 与预览同一导航函数。Dock 已有历史结果的回源路径接入预览，`/resume` 选择器继续由自身的对话框焦点契约负责。交接走原 Dock 的呈现和宿主切换，按现有减少动态偏好。跨 Host Workspace 需要在可断开的独立 Host 按既有权限复验。

## 验收

用合成 Codex 历史记录让真实 Vault 扫描并经产品的「在新聊天中恢复」打开 Native Chat。把该真实 Chat 放入双 Pane Workspace，经过目录、Vault 查询和原位跳转，核对此时仍是同一 Workspace 与原 Chat、两个未发送草稿和目标输入焦点。然后返回工作树，核对目录状态。最终两次回放在索引就绪时进入历史结果，跨 Host 断线重试沿用第五轮的独立证据。 [历史查询](evidence/iteration-15-17-windows/i17-history-search.png) · [原位交接连续帧](evidence/iteration-15-17-windows/history-to-workspace/timeline.json) · [状态断言](evidence/iteration-15-17-windows/session-index-checks.json) · [第五轮](ITERATION_05.md)
