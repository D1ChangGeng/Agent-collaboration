# 第 72 轮 · Windows 与 Linux 实机配对

接续已通过的第 69–71 轮。Windows 客户端和 Linux 原生运行端从同一 Porpita 源码提交构建。进入既有「添加服务器」对话框，输入 Linux 服务生成的访问链接。

经认证的 SSH 转发到达 Linux 运行端时，客户端显示链接中的本地地址和隧道确认。用户明确确认这条连接后，界面按实际服务端回应更新目录与可用状态。使用服务端实际返回的 Runtime ID 关联配对结果，运行身份与链接显示的地址各有证据。

沿用服务器卡片的连接、版本与更新状态。试跑的直接启动遗漏版本参数，Linux 健康回执使用回退版本，卡片显示手动更新提示。按托管端的方式以产物 `.version` 启动，客户端和服务器均报告 0.1.0，卡片显示连接、SSH 隧道和版本。 [卡片画面](evidence/iteration-72-74-physical-en/i72-physical-pairing.png)

对应 M.02.31。复用服务器设置、访问链接表单、配对验证和状态读数。配对凭据使用隔离档案，截图在提交完成后记录。 [实机回放工具](tools/observe-physical-porpita.cjs)

实机回放使用英语浅色 1000×720。客户端与运行端均报告 0.1.0，客户端查询到的配对目标 Runtime ID 与 Linux 启动回执一致。本轮保留现有配对与展示方案。 [运行和断言](evidence/iteration-72-74-physical-en/physical-porpita-checks.json)
