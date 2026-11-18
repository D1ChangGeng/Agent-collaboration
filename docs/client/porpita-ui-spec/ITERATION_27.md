# 第 27 轮 · 用量跟随选中的 Chat

上一轮同时显示本机 Chat 和 Studio Explorer。选中本机输入后，状态栏仍显示 Studio 的用量。原因是原用量区从传统工作树解析账户，组合式 Workspace 则把所选会话保存在独立布局里。 [第 26 轮窄窗](evidence/iteration-24-26-loopback-zh/i25-narrow-workspace.png) · [原始观察](DECISIONS_AND_SEQUENCE.md)

VS Code 的远程窗口在状态栏标出当前连接，JetBrains Client 把后端名称放在与后端数据相邻的位置。两种范例都让用户先辨认数据来源。在 Porpita，一个窗口可以并排放两台机器的 Chat，辅助面板也可以固定在第三种工作范围。比较窗口单一 Host、按控件焦点切换 Host、延续所选 Chat 三种方式后，用量采用第三种。文件筛选取得键盘焦点时仍显示原来选中的 Chat 的用量。独立 Explorer 的状态栏让出会话用量区域。 [VS Code 远程指示器](https://code.visualstudio.com/blogs/2019/07/25/remote-ssh#connect-using-remote---ssh) · [JetBrains 后端状态](https://www.jetbrains.com/help/idea/work-inside-remote-project.html#backend-control-center)

沿用 Orca 的一行状态栏、已有密度分档、用量组件和工作树 Host 徽章。配额数据、读数及空态操作都从同一 Chat 的可用来源解析。设置、原工作树和独立编辑器继续走各自的原入口。应用级连接计数、插件、更新与本机进程指标各自保持原有含义，端口和资源面板的具体作用域仍按 A.03.01 追踪。

重点验证两条同名 Chat 的来回切换、600×460 下本机 Chat 与 Studio Explorer 的不同归属、以及独立 Explorer。源码见 `workspace-preview-usage-scope.ts`、`focusedPreviewSession` 和 `StatusBarUsageCluster.tsx`。对应 A.03.03、D.07.03 和 J13。

Windows 回放确认本机和 Studio 两条 Chat 的用量入口各属于其来源。Studio Explorer 的筛选框取得焦点后，左侧仍是本机 Chat，底部仍标出本机。独立 Explorer 隐去会话用量区。 [切换连续帧](evidence/iteration-27-29-usage/usage-follows-chat/timeline.json) · [600×460 画面](evidence/iteration-27-29-usage/i25-narrow-workspace.png)
