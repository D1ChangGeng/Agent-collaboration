# 第 70 轮 · 独立 SSH 项目的接入入口

原工作树的来源是已保存的 SSH 主机且项目尚未由 Porpita 服务提供时，沿用现有「从 Porpita 移除」对话框。主机名称和工作区仍指向发起动作时的对象。沿用取消、工作区记录移除和边界说明，增加「打开 SSH 设置」动作。

进入设置保留该工作区记录，由用户走现有 Host 接入和项目配置流程。项目由所属服务提供后，从该项目重新进入分支复核。对话框里的记录移除仍只作用于本地登记。主机记录已经删除时，使用原有孤立工作区提示和可用动作。

此处借鉴 SSH 连接与远端应用服务各自承担的职责，具体接入、身份和 Git 权限直接沿用 Porpita 的主机管理。对应 M.02.29。 [VS Code Remote SSH 的服务边界](https://code.visualstudio.com/docs/remote/ssh) · [SSH 界面回放](tools/observe-space-ssh-recovery.cjs)

界面回放使用有历史 SSH 登记的隔离档案，任务对象引用同一台实机 Git 夹具的路径。SSH 设置动作保留原登记。物理主机上的工作树和两台机器上的同名分支由已有 SSH 通道另行读取并确认。 [原确认](evidence/iteration-69-71-ssh-zh/i70-ssh-project-needs-host-service.png) · [设置入口](evidence/iteration-69-71-ssh-zh/i70-ssh-settings-with-workspace-preserved.png) · [实机 Git 断言](evidence/iteration-69-71-physical-ssh/physical-ssh-checks.json)

首轮 760px 的设置标题和说明被工具栏挤窄。现有设置标题区在可用宽度不足时让工具栏换行。1160px 下标题与工具栏同排，两种宽度都使用原主机卡片和操作。 [窄窗](evidence/iteration-69-71-ssh-layout-zh/i70-ssh-settings-with-workspace-preserved.png) · [宽窗](evidence/iteration-69-71-ssh-layout-zh/i70-ssh-settings-wide.png)
