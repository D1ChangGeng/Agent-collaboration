# 第 71 轮 · WSL 停止后的启动、核对和重试

Space 已有读数、路径和选择时，只读核对先确认该项目的 WSL 运行状态。发行版停止后显示「WSL 不可用」，保留上次真实路径、勾选和原复核。将原来的行内动作更新为「启动 WSL 并核对」，可访问名称包含发行版及分支。

显式启动仅针对该行已验证的本机项目发行版。回到同一行后用新 Git 读数刷新，并保留键盘操作位置。启动中或结果未确认时，含该项的提交保持暂停。用户仍按原 Git 规则确认该项，重新占用时按原回执重试。

本轮准备一次性 WSL 2 发行版可单独启动和停止。验收看实际停止、被动核对后的运行状态、用户启动动作、检出结果、两条引用和最终删除回执。对应 M.02.30。 [Microsoft WSL 命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands#terminate) · [测试发行版工具](tools/space-wsl-recovery-distro.cjs)

在导入的 WSL 2 夹具中使用 Git 2.34.1 完成十步。停止后按普通核对保持发行版停止，原行的启动动作取得新读数并保留两条引用。随后真实再次占用会拒绝提交，解除后从零选复核显式重试。一次性发行版在回放后注销。 [停止时](evidence/iteration-69-71-wsl-zh/i71-space-wsl-stopped.jpg) · [启动后](evidence/iteration-69-71-wsl-zh/i71-space-wsl-started.jpg) · [断言](evidence/iteration-69-71-wsl-zh/space-branch-review-checks.json)
