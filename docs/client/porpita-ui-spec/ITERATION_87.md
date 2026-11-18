# 第 87 轮 · 导入同前缀 SSH 主机

第 84–86 轮获用户确认。延续 GNOME Shell Wayland 的 720px 平铺条件，以「Sync ~/.ssh/config」导入三个同前缀别名。三个条目各有 IPv6 环回端口，用户名继承自匹配三个条目的 `Host` 规则。 [基线导入](evidence/iteration-87-89-gnome-baseline/i87-baseline-import.json) · [OpenSSH 配置继承](https://man.openbsd.org/ssh_config)

基线导入保留了三个别名和端口，保存的用户名为空。修订沿用原有导入、去重和来源分组，从已有的 OpenSSH 路由解析取得连接用的主机、端口和用户名。手动登记的条目保留自己的配置。

实机从空列表以键盘启动同步，新登记的三个条目都在「From ~/.ssh/config」组中。各条实际地址与独立 `ssh -G` 得到的 IPv6 主机、端口和继承用户名一致。 [导入后的画面](evidence/iteration-87-89-gnome-en/i87-import.png) · [导入与解析核对](evidence/iteration-87-89-gnome-en/i87-import.json)
