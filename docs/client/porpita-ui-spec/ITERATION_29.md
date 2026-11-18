# 第 29 轮 · 用量等待、离线与配对撤回

工作空间里正在使用的 Chat 可以失联。状态栏需要说明等待的是哪台机器，并让另一条会话继续使用自己的来源。恢复后的数据经原配对再次读取。配对撤回时原 Chat 留在可处理的位置，状态栏旧读数、Host 名称和账户入口一起退场。

| 所选 Chat | 用量区 |
| --- | --- |
| 来源待确认 | 显示正在检查 Chat 所属主机 |
| Studio 已连接，账户快照待返回 | 显示正在读取 Studio 用量 |
| 已收到该 Host 的空账户快照 | 显示在该 Host 设置用量 |
| Host 已确认，账户读取失败 | 显示该 Host 的用量无法读取 |
| 原 Host 临时离线 | 保留 Host 名称与离线状态，重连动作位于原 Chat 或 Explorer |
| 配对撤回或会话归属失效 | 显示聊天用量不可用 |

沿用当前账户流、Runtime 状态通知和布局身份。用量流和主动刷新包含原配对版本，已显示读数也带配对及连接代次。切换会话关闭旧来源的用量菜单。新连接的账户快照返回前显示等待，过期回包不能替换当前内容。

集成验收依次停止 Studio、切回 Local、连回原 Studio、撤回配对并回到 Local。使用模型测试补同一 Host ID 被重新配对时的延迟刷新。没有配置的账号用实际空快照作回放。有授权数据的账户与物理跨机网络仍是独立验收面。源码见 `use-owner-usage-rate-limits.ts`、`runtime-provider-accounts-client.ts` 与 `StatusBarUsageCluster.tsx`。对应 A.03.05、S.06、J12 和 J13。

实际停止 Studio 后检查离线提示及账户入口隐藏，随后继续编辑本机草稿。恢复后重新看到 Studio 用量入口，撤回配对时显示聊天用量不可用。本机选中后再出现本机用量入口。 [停机连续帧](evidence/iteration-27-29-usage/explorer-source-outage/timeline.json) · [恢复后的来源切换](evidence/iteration-27-29-usage/usage-after-reconnect/timeline.json) · [撤回画面](evidence/iteration-27-29-usage/i26-explorer-revoked.png)
