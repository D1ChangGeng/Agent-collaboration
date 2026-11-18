# 第 69 轮 · 重连原配对主机并继续复核

接续已通过的第 66–68 轮。用户在远端分支复核中遇到连接中断时，保留原行、上次路径、分支勾选和键盘焦点。「重连并核对」沿用现有 Outline Button，反馈连接和核对进行中。恢复由该行原配对版本指示，成功后再查询当前 Git。平台的连接状态和 Git 读数分别以实际结果更新。

断线项保留勾选，仍阻止包含该项的提交。重连后 Git 未能确认时保留这项限制。查到当前检出或未检出后，用户可显式提交，随后仍由原主机校验 HEAD 与实际检出。配对版本变化时停在原复核并撤下受影响项。其余分支可在用户取消勾选待恢复项后继续处理。

已登记的第二台 Linux 工作站提供真实 SSH/Git 路径与双机引用证据。Windows 隐藏客户端与同机配对服务负责按钮、焦点和状态验证。完整双机 Porpita 配对需要在该 Linux 主机启动与本轮代码对应的运行产物。对应 M.02.28。 [双机 Git 工具](tools/observe-physical-ssh-git.cjs) · [配对回放](tools/observe-space-remote-checkout.cjs)

Windows 与 Linux 上的隔离仓库拥有同名、同 HEAD 的分支。通过 SSH 在 Linux 移动真实检出，重新执行查询读到新路径。Porpita 配对回放另验证，过期版本的请求保持断线，当前配对可在原行恢复。连接恢复后 Git 暂时找不到该分支时仍暂停提交，恢复引用并核对后才重新允许提交。 [实机 Git 断言](evidence/iteration-69-71-physical-ssh/physical-ssh-checks.json) · [原行重连](evidence/iteration-69-71-paired-en/i67-paired-host-offline.png) · [配对断言](evidence/iteration-69-71-paired-en/paired-branch-checks.json)
