# 第二十轮 · 按 Host 识别、打开和恢复会话

同名会话都可以出现在目录。先看 Host，再按明确来源打开原工作树的 Chat。连接不稳定时，目录仍提供本机和其他可用 Host 的工作路径。

## 设计与采用

既有 Vault 的同名条目携带 Host 标签，单机断开时保留其他来源的结果。GitHub Codespaces 的远端资源列表也展示来源并保留单条进入动作。在目录采用 Porpita 已有的 `WorktreeHostContextBadge`、原工作台精确定位及 Runtime 的连接与工作树更新动作。行内 Host 标记在「最近」和「项目」两种排序下都可读，独立 Host 筛选也可与原位置筛选组合使用。 [同名 Vault 基线](evidence/iteration-05-windows/i5-two-sources.png) · [Codespaces 打开远端资源](https://docs.github.com/en/codespaces/developing-in-a-codespace/opening-an-existing-codespace#reopening-an-existing-codespace)

| 情况 | 设计规则与实际行为 |
| --- | --- |
| 本机与配对 Runtime 发布 Chat | 实际 Host、工作树、Tab、组和原生会话共同限定来源。混合结果显示每条 Host；项目分组按 Host 与项目 ID 保持独立。以 Host 标签和标题独立查找。 |
| 选择已有配对 Chat | 在进入前重新核对 Host 联系、工作树与真实 Tab。使用对应 Runtime 的路由进入其原工作树。已有本机 Workspace 仍可作为对应本机 Chat 的目的地。 |
| 暂时无法确认 Host 联系 | 已知行保持在目录，显示连接未确认，阻止激活。选择该 Host 后提供原「重新连接」路径。成功后保持原查询和筛选，焦点回搜索输入，用户可用方向键选择恢复的行。 |
| 取消配对、来源退役或权限拒绝 | 目录跟随实际授权撤回移除内容。显式选中的失效 Host 保留筛选意图，用户可选其他 Host 或所有主机。 |

主要源码为 `session-index-hosts.ts`、`session-index-model.ts`、`SessionIndexHostNotice.tsx` 和 `workspace-tab-palette-activation.ts`。工作台的显式 Host 校验在选择前后均成立。配对 Runtime 路由和直接 SSH 各有自己的支持条件。跨 Host Workspace 持久化还需要给布局引用增加 owner 信息并完成双机验收。

## 验收范围

在同一台 Windows 机器启动两个隔离 Runtime，使用相同的 Provider 历史 ID 和标题、不同的 transcript 和工作树。验证目录显示两条来源，打开原 Chat、读到原记录和原草稿，Studio 断线时本机仍可用，再连接后沿用查询继续原 Chat。带独立物理设备的延迟、相同原始工作树/结构化 ID 碰撞和授权在线撤回分别记录。

英语和简中两组回放均验证来源、Host 筛选、目标 Composer、断线禁用和恢复。重新连接后曾出现 Chat 恢复可用而运行状态尚未收到更新，目录仍显示无近期更新标记。 [860×520 同名会话](evidence/iteration-20-loopback/i20-directory-hosts.png) · [显式重连](evidence/iteration-20-loopback/directory-host-reconnect/timeline.json) · [简中恢复](evidence/iteration-20-loopback-zh/i20-directory-reconnect.png)
