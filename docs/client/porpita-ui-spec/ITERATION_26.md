# 第 26 轮 · Explorer 重启恢复、掉线和配对撤回

用户重启客户端后回到同一文件范围和选中的条目。配对服务器暂时不可达时，其他窗格和本机 Explorer 可继续使用。恢复连接后原位置读取新的目录内容。配对已撤回时只留下可移除的 Explorer 占位。状态组织沿用第 23 轮的单对象重连与移除，以及第 12 轮的档案保存和读取失败流程。 [档案恢复](ITERATION_12.md) · [单侧重连](ITERATION_23.md)

v3 保存 Explorer 的 Host、配对版本、Worktree、根、呈现位置、目录、筛选和选择。读取 v1 或 v2 时将原 Explorer 解释为本机范围，保留 v2 已保存的配对 Chat。主进程按既有原子方式保存本次编辑。离线时停止呈现该来源的结果，原 Host 由已有的重连入口处理。配对版本变化、授权撤回或源不可确认时拒绝读目录和打开文件。移除操作只作用于 Explorer 的布局实例。回到嵌入它的 Workspace 时，输入可继续交给合法的 Pane。

关闭客户端的回放保留 Studio 服务器。断线回放停止 Studio，恢复时用相同档案启动。隔离目录在停止期间新增一条标记文件，重连必须看到新文件及旧选择。本机仍可使用自己的 Explorer 和未发送草稿。通过设置撤回 Studio 配对后复验原路径与文件行的呈现，再用占位中的按钮移除实例。两台物理机、直连 SSH 和不同 OS 验收沿用各自条件。 [验收路径](PLAYBACK_SCENARIOS.md)

主要源码为 `porpita-workspace-layout.ts`、`workspace-preview-explorer-scope.ts`、`use-workspace-preview-explorer-directory.ts`、`WorkspacePreviewExplorer.tsx` 和 `SessionIndexHostNotice.tsx`。对应 G.09.04、S.06、J06、J07 和 J12。

Windows 回放核对了新客户端进程、原 Studio Runtime 和原 Explorer 位置。重连读到新增文件且保留两边的工作。撤回配对后只显示不可用占位。移除 Explorer 后是同一 Workspace，本机输入重新获得焦点，另一个 Explorer 和磁盘文件可用。 [冷恢复](evidence/iteration-24-26-loopback-zh/i26-cold-explorer.png) · [重连连续帧](evidence/iteration-24-26-loopback-zh/explorer-source-recovery/timeline.json) · [撤回配对](evidence/iteration-24-26-loopback-zh/i26-explorer-revoked.png) · [运行断言](evidence/iteration-24-26-loopback-zh/workspace-explorer-continuity-checks.json)

本机回归读取真实 v1 档案，保持已打开的工作对象，首次实际分屏编辑保存为 v3。原本损坏的档案依旧保留，恢复有效文件后可从「重试」进入。v2 与 v3 的分界补有针对性的解析测试。 [本机回归](evidence/iteration-26-local-profile/run.json)
