# 第 88 轮 · IPv6 地址呈现与原生读屏

原列表在 720px 仍显示完整别名，但 `::1` 与端口直接相接。当前规范使用 `用户名@[IPv6]:端口`，同时保持原有 SSH 主机条目的换行与动作位置。方括号界定 IPv6 字面量。 [基线焦点](evidence/iteration-87-89-gnome-baseline/i88-baseline-beacon.png) · [IETF 主机部分](https://www.rfc-editor.org/rfc/rfc3986#section-3.2.2)

使用真实 Tab 焦点和 GNOME Orca 录音，校对连接按钮的动作、完整别名、用户名、IPv6 地址和端口。首次信任弹层使用本次握手的实际连接地址，为同一次操作提供一致的目标身份。

720px 下三个别名和地址均可读全。Orca 51.1 逐行读出完整连接身份，Beacon 的地址为 `changgeng@[::1]:51007`。回放使用 IPv6 环回和三个非默认端口。 [画面与语句](evidence/iteration-87-89-gnome-en/i88-focus-beacon.json) · [三个焦点片段录音](evidence/iteration-87-89-gnome-en/config-host-focus.wav)
