# 第 24 轮 · 从混合工作空间选择 Explorer 的原目录

用户在同一个 Workspace 里处理本机与配对 Host 的 Chat。打开 Explorer 时，目标是找到明确来源的工作树，读取它的目录，并把文件交还给该来源的原编辑器。第 11 轮的固定本机 Explorer 与第 21 轮的会话来源标识提供了现成的组件和用法。 [固定 Explorer](ITERATION_11.md) · [跨 Host Chat](ITERATION_21.md)

VS Code 的多根工作区用目录名称区分重名文件，Quick Open 和编辑器标签也保留目录线索。Porpita 的两个来源可以各自有同名项目和相同相对路径，因此在选择前用项目、目录和 Host 一起标明归属。比较过沿焦点直接打开、把多个来源放进同一树、先选择固定目录三种路径。单一候选直接打开。多个不同来源时使用现有命令选择器和会话目录的 Host 徽章。创建后，一个实例只读自己的目录。 [VS Code 多根工作区的源标签与 Quick Open](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces#general-ui)

顶栏「新建工作对象」→「打开 Explorer」。多个来源时可搜索目录或主机，按 Enter 选择。相同实例由 Host、配对版本、Worktree 与根去重。同名文件在两个实例中分别读取，双击或从筛选框按 Enter 交给原编辑器。目录读取与文件打开沿用 Orca 的操作归属校验以及 Workspace 预览的现有可见控制。无可用来源时保留当前工作空间并说明下一步。

预览采用现有单目录文件列表、父目录返回、名称筛选、文件图标和编辑器。目录分页只筛选已加载的条目，仍有后续页时显示继续加载入口。完整多级树、Contents、写操作、直连 SSH 和同一原始 Worktree ID 对应多个 Host 的编辑器归属继续按 J07/J08 追踪。 [J07](PLAYBACK_SCENARIOS.md) · [能力矩阵](SIDEPANEL_CAPABILITY_MATRIX.md)

主要源码是 `WorkspacePreviewExplorerPicker.tsx`、`workspace-preview-explorer-scope.ts`、`file-explorer-directory-listing.ts` 和 `quick-open-file-navigation.ts`。对应 G.09.02、H.01、J07 和 J08。

Windows 预览以两个隔离 Runtime 打开同名项目 `Release-review`。同一相对路径 `handoff/handoff-note.md` 分别显示 Local 与 Studio 的实际文档，并核对编辑器持有的 Worktree 和 Runtime。 [选择来源](evidence/iteration-24-26-loopback-zh/i24-source-picker.png) · [本机文件](evidence/iteration-24-26-loopback-zh/i24-open-original-local.png) · [Studio 文件](evidence/iteration-24-26-loopback-zh/i24-open-original-studio.png)
