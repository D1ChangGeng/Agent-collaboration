# 第 86 轮 · 核对所选 SSH 目标与连接回执

在当前条目核对完整别名、用户、主机和端口后，从连接按钮按 Enter。该按钮进入连接中，成功回执留在对应条目内，Orca 获得带同一目标身份的「Connected」状态。

实机回放使用三个已登记主机密钥的 OpenSSH 监听。先用 Space 勾选 atlas，再在 beacon 的连接按钮按 Enter。对照三个监听的实际认证记录，检查连接仅发往 beacon，并核对连接前后及断开后的键盘焦点。

首次修订能连接正确目标，Orca 语句却把「Connected」和别名连在一起。最终设计以一个带停顿的完整状态句提供给 Orca，保留同一条目中的可见状态。 [试跑语句](evidence/iteration-84-86-gnome-trial/i86-connected.json)

勾选 atlas 时，在 beacon 的连接按钮按一次 Enter，只有 beacon 新增一条 TCP 连接和一条公钥认证。Orca 自动读出「Connected, porpita-integration-validation-workspace-beacon, changgeng@127.0.0.2:45165」。原按钮保持焦点并变为「Disconnect」，断开后同一按钮恢复「Connect」。 [连接结果与监听计数](evidence/iteration-84-86-gnome-en/i86-connected.json) · [连接录音](evidence/iteration-84-86-gnome-en/connection-confirmation.wav) · [断开后](evidence/iteration-84-86-gnome-en/i86-disconnected.png)
