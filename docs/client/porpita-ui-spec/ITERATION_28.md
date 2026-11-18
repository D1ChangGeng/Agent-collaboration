# 第 28 轮 · 用量入口、账户设置与原编辑器

用户根据状态栏上的 Host 判断用量所属，再进入该 Host 的账户设置。返回后继续同一个 Workspace 和原 Chat。若用户从固定 Explorer 打开文件，原编辑器的状态使用文件所在的工作树。从原编辑器返回后，继续按顶层工具或所选 Chat 恢复状态栏含义。

复用现有用量菜单、Provider Details、账户设置的 Host 选择器和应用返回入口。空态按钮写出将打开的 Host。已有指标时，菜单标题与页签下方的来源徽章都标出 Host。预览中的用量行可查看原生详情，账户操作经明确的同范围账户页。跨 Host 用量菜单中的账户页入口以当前数据的 Host 为目标。桌面用量历史属于这个客户端，保留在本机路径。按键进入和返回都保持现有 UI 模式。

已有账户数量及配额代码按实际快照渲染。Windows 隔离 Runtime 的回放用于观察未配置账户状态、账户页里的 Host、原编辑器的工作树、返回后的 Chat 及草稿。实际账户的登录和切换需使用有权限的独立账号验证。源码见 `StatusBarUsageEmptyCta.tsx`、`StatusBarUsageCluster.tsx`、`UsageRosterPanel.tsx` 和现有 Settings Host 选择器。对应 A.03.04、H.01、J11 和 J13。

真实账户页用键盘操作核对了两种 Host 后回到原布局。窄窗另用 37% 合成值核对来源名、读数和菜单。两条相对路径相同的文件也各交给原编辑器，返回独立工具时回到工具的语义范围。 [账户设置连续帧](evidence/iteration-27-29-usage/usage-accounts-handoff/timeline.json) · [37% 用量夹具](evidence/iteration-27-29-usage/i28-populated-usage.png) · [Studio 原编辑器](evidence/iteration-27-29-usage/i24-open-original-studio.png)
