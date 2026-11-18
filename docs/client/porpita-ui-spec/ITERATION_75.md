# 第 75 轮 · Linux 图形客户端的双机配对

第 72–74 轮获用户确认。本轮以 Linux 图形客户端为操作者，经原生设置与真实 Windows 主机配对。沿用远端服务器列表、添加服务器对话框、访问链接、隧道确认与现有连接回执。

键盘从设置进入服务器列表。添加服务器后，输入区取得焦点。Escape 取消时返回添加入口。只有实际的 Windows Runtime 应答确认后，列表标记连接完成。回放对照两端版本、Windows Runtime ID、Linux 窗口焦点及系统读屏的实际播报。记录对话框时使用空字段。 [第 72 轮](ITERATION_72.md) · [原生回放工具](tools/observe-linux-native.cjs)

Linux x64 图形客户端以仓库原有 Electron 打包路径安装到验收机的用户目录。独立 X11 会话使用实际 GNOME Orca 和 AT-SPI，X11 按键与窗口像素留有证据。 [版本与证据身份](SOURCE_BASELINE.md)

首轮 Linux 对话框在关闭时把焦点留在页面主体，Orca 随后缺少明确的继续位置。修订由既有 Dialog 管理初始焦点，关闭后复用同一设置页的添加按钮。配对成功仍使用现有通知。 [试跑焦点记录](evidence/iteration-75-77-linux-trial/i75-pair-cancel.json)

最终回放记录原生窗口中的字段焦点与读屏说明，按 Escape 后回到 Add server。随后以实际 Windows Runtime ID 核对连接，Orca 播报成功。 [配对画面](evidence/iteration-75-77-linux-en/i75-windows-paired.png) · [播报](evidence/iteration-75-77-linux-en/i75-windows-paired.json)
