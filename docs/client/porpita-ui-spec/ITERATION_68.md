# 第 68 轮 · WSL 检出位置与复核

Windows 上通过 WSL 目录访问项目时，保留分支行同时显示本机与发行版。检出路径沿用项目所在发行版的 Windows 可访问形式，Linux 路径尾部保留大小写、空格与 Unicode。用户可在当前行查看路径，只有同仓库、同 Host 且符合实例条件的登记工作树才提供打开动作。 [Microsoft WSL 文件系统互操作](https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop)

只读核对先检查目标发行版的可用状态，然后沿用该项目的 Git 路由。确认发行版已停止时保留上次路径和勾选，提示启动该发行版后再核对。运行状态或引用无法确认时，显示「结果未确认」。重新核对以这次读数为准，提交保持原分支、HEAD 和工作树检查。

对应 M.02.27。首轮在实际释放占用后卡在确认阶段。Git 列表的 Linux 绝对路径缺少用于对照工作树记录的发行版。修正后，使用真实 Ubuntu WSL 2 临时仓库复跑移动、发行版、大小写、释放、再次占用和显式提交。停止中的发行版实况需要可单独启停的测试环境。 [首轮记录](evidence/iteration-66-68-trial/wsl-first-run.json) · [路径画面](evidence/iteration-66-68-wsl-zh/i63-space-checkout-current.jpg) · [清理回执](evidence/iteration-66-68-wsl-zh/i65-space-checkout-retry-resolved.jpg)
