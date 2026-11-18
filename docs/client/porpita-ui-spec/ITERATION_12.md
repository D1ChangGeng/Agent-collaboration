# 第十二轮 · 重启后找回工作空间

用户关掉 Porpita 后，能从原入口找回分组、并排会话、Pane 比例及固定目录工具。已通过的第九至十一轮给出了同一渲染器重载的证据。本轮以完整退出再启动检验桌面档案的连续性。

## 设计与采用

对照了随会话保存、随 Worktree 保存和由桌面档案单独保存。一个工作空间可以引用多个 Worktree，所以布局记录由当前 Porpita 档案持有。Native Chat 的草稿和执行状态继续由各自会话管理。已有 VS Code Workspace 将用户工作环境与编辑器状态连在一起，Porpita 延续选择同一工作对象的交互。窗口上的一行分组、标题栏及工作区内容采用已确认预览。 [VS Code Workspace](https://code.visualstudio.com/docs/editing/workspaces/workspaces) · [第九轮](ITERATION_09.md) · [第十一轮](ITERATION_11.md)

- 进入预览时读桌面档案内的版本化记录。一次保存包括分组、打开状态、当前对象、会话引用、比例、工具绑定目录、筛选和选中项。原生会话、草稿和文件继续使用原所有者。
- 档案首次缺少文件时，导入此前开发预览的有效 renderer 记录。主进程的文件是后续加载来源。沿用项目已有的原子文件替换，写入失败保留内存里的布局和重试入口。
- 文件不可读时在入口显示反馈，用户可以重试或回到 Worktree。已有布局即使某个原生引用暂时不可用也应保留其位置。预览入口仍由开发构建开关控制。

源码为 `porpita-workspace-layout.ts`、`porpita-workspace-profile.ts`、`workspace-preview-persistence.ts` 与 `WorkspacePreview.tsx`。关联 A.05、D.07、R.06 及 J03/J06/J12。

## 验收

构造两个真实本地 Codex Chat 和同一嵌入 Explorer。逐项核对磁盘记录、迁移、完整进程退出与启动后的分组、Pane 比例、草稿和文件筛选。回放使用独立档案与未登录 Codex，会话没有发送提示词。

回放将一次性档案切到不受支持的记录版本，确认数据保持原样，恢复有效记录后在同一入口重试。正常退出后执行新的 Electron 进程并确认档案路径和窗口隔离。 [冷启动恢复](evidence/iteration-12-14-windows/i12-cold-restore.png) · [读取失败](evidence/iteration-12-14-windows/i12-read-failure.png) · [回放记录](evidence/iteration-12-14-windows/run.json)
