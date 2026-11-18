# 第 36 轮 · 让端口详情说明实际打开地址

[第 33 轮简中详情](evidence/iteration-33-35-port-resources-zh/i33-port-details.png)同时列出「地址」与「绑定」，并显示 `workspace`、`unknown` 和 `command`。在本机与配对工作树之间切换时，用户需要先知道端口在哪个 Host 监听，再确认 Browser 会去哪里。

| 条件 | 显示与行为 |
| --- | --- |
| 本机工作树 | Host、工作树、监听地址和浏览器地址用现有详情网格显示。监听地址保留 OS bind，IPv6 用括号表示。浏览器地址与底部「在应用内浏览器打开」使用同一 URL，包括服务公布的 origin 或原逻辑推导出的地址。 |
| 配对工作树 | 详情显示所属 Host、监听地址及可用的服务公布地址。端口操作经原工作台的 Host 侧入口。 |
| 信息不足 | 协议与缺失的诊断值显示「未知」。来源证据区分工作目录、命令行与归属未确定。服务类型、协议和证据使用用户可读文案。 |

复用 Orca 的端口详情对话框、Host 徽章、原按钮和共享间距。原 Ports 侧栏保有 Address 字段。预览详情的长值换行，标题仍是该端口号。Escape 返回当前 Host 的端口入口。VS Code 的端口视图也给实际打开地址单独标签和操作入口。 [VS Code Ports](https://code.visualstudio.com/docs/debugtest/port-forwarding)

源码对应 `local-port-details-dialog.tsx`、`WorkspacePreviewPortDetails.tsx` 和 `workspace-port-urls.ts`。矩阵 A.03.12 连接 G.05 和 J07/J11/J13。

回放分别读取实际本机和 Studio 监听。在同一交互中核对两个地址、简中诊断项、600×460 的宽度和 Escape 返回焦点。样本为 IPv4，由源码确认 IPv6 括号规则。 [英语连续帧](evidence/iteration-36-38-port-targets/port-address-provenance/timeline.json) · [简中连续帧](evidence/iteration-36-38-port-targets-zh/port-address-provenance/timeline.json)
