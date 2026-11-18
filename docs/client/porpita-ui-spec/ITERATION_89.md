# 第 89 轮 · 首次 SSH 主机密钥确认

基线的 `StrictHostKeyChecking ask` 在未出现确认弹层时就完成了公钥认证。本轮将未知标准 SSH 主机的 `ask` 行为接入现有 SSH 请求队列，并用既有安全弹层显示别名、实际地址、算法和指纹。OpenSSH 配置显式允许自动接纳新密钥时，沿用对应的策略。 [基线首次连接](evidence/iteration-87-89-gnome-baseline/i89-baseline-first-connect.json) · [OpenSSH 主机密钥策略](https://man.openbsd.org/ssh_config#StrictHostKeyChecking)

首次打开时焦点在「Cancel」。Escape 取消并返回触发连接的按钮。再次打开后，用 Tab 到「Trust and connect」，先核对完整别名、地址和指纹，再以 Enter 确认。确认结果绑定当前握手和发出确认的窗口，写入记录后继续认证。已知密钥校验、变更或撤销密钥的拒绝规则独立适用。 [WAI 模态弹层键盘规范](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

实机弹层的 Ed25519 指纹与监听自身公开指纹一致。Orca 在打开弹层时读出别名、连接地址和指纹，在确认按钮上重复目标身份。Escape 后回到同一连接按钮，状态表明密钥尚未确认，认证计数和信任表均未变化。再次确认只增加 Beacon 的认证记录和 `[::1]:51007` 对应的信任记录。断开重连时同一密钥验证通过，直接进入认证。 [取消](evidence/iteration-87-89-gnome-en/i89-cancel.json) · [确认画面](evidence/iteration-87-89-gnome-en/i89-trust-action.png) · [读屏录音](evidence/iteration-87-89-gnome-en/host-key-confirmation.wav) · [重连](evidence/iteration-87-89-gnome-en/i89-reconnected.json)
