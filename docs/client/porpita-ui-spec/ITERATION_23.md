# 第 23 轮：一个 Host 断线时继续另一侧

让两个来源的 Chat 留在同一 Workspace 内。Studio 临时失联时，用户仍可编辑 Local 的未发送草稿，Studio 的原位置保留。重连入口显示在对应会话内，恢复后可回到同一 Composer 和草稿。对比独立重开远程窗口的方式，在原 Pane 内恢复可保留正在进行的本机工作和分屏比例。 [第 20 轮目录恢复基线](ITERATION_20.md) · [VS Code 远程会话的重连条件](https://code.visualstudio.com/docs/agents/run/remote-agent-sessions#troubleshoot-remote-sessions)

实际已挂载的 Native Chat 沿用原连接提示。对仍拥有相同配对来源的 Pane，等待自动恢复期间也可使用原生重连动作。若会话尚未挂载且 Host 暂时不可达，Pane 使用目录里的 Host 重连组件。配对撤回、换源或会话身份不能确认时，Pane 显示不可用状态并提供移除布局引用的入口。重连前后仍可继续使用另一侧的工作内容。

回放会停掉隔离 Studio 进程，并验证 Local 输入仍可编辑，再启动同一 Studio 档案并检查原来两份草稿。配对换源与原生身份冲突由专门的拒绝路由验证支撑。独立机器网络、实际模型请求和授权在线撤回另有环境要求。 [待闭环](COVERAGE_CLOSURE.md)

中英文回放都通过了单侧停止、恢复、客户端设置中撤回隔离配对和移除占位 Pane。撤回后保留失效位置，隐藏原提交记录及输入区。移除后本机仍在原 Workspace，离线期间的编辑保留，输入焦点回到本机。 [断线](evidence/iteration-21-23-loopback-zh/i23-studio-outage.png) · [重连](evidence/iteration-21-23-loopback/workspace-host-recovery/timeline.json) · [撤回后的占位](evidence/iteration-21-23-loopback-zh/i23-pairing-removed.png) · [移除后](evidence/iteration-21-23-loopback/i23-remove-stale-reference.json)
