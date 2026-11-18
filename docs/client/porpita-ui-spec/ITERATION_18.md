# 第十八轮 · 找到并继续未打开的历史会话

会话目录的「显示」菜单提供「未打开的历史会话」。用户留在左栏，搜索、确认来源，再从原 Vault 行进入历史记录对应的 Chat 或终端。打开状态和历史继续使用各自的查询与作用域。

## 设计与采用

现有会话目录适合持续切换已经打开的 Chat，右侧 Vault 有完整记录查询、来源、原位定位和恢复动作。对照 VS Code 通过独立状态筛选找回已归档会话。Porpita 先沿用 Vault 的独立历史视图。把两类记录放入同一搜索组会使 Enter 的含义随结果而变化，且同一会话可在已开目录和历史源重复出现。左栏采用已在产品运行的 `AiVaultPanel`、虚拟行、搜索/扫描、范围、Host 与原动作菜单。保留第十七轮从已开目录向右侧 Vault 交接的入口。 [VS Code 会话查找和恢复](https://code.visualstudio.com/docs/agents/run/sessions/manage-sessions#find-and-resume-a-session) · [Porpita Vault 基线](evidence/iteration-04-windows/i4-actions.png)

| 使用情况 | 设计规则与实际数据 |
| --- | --- |
| 在目录进入未打开历史 | 将已开目录的查询用作历史入口初值。Vault 自主管理后续查找、本次历史范围和 Host。空记录、无匹配、索引准备、部分结果和重试沿用 Vault 状态。 |
| 现有会话可定位 | 结构化记录按来源 Host、工作树和原生会话校验。其他记录使用 Vault 已知的原终端 Pane 绑定。找到可定位原位后，从未打开视图收起该行。 |
| 明确继续历史 | 原动作菜单的「在新聊天中恢复」执行现有 Harness 续接并聚焦真实输入。其他恢复或查阅动作由该历史记录的权限和能力决定。恢复使用原 Vault 选定的执行工作树。 |
| 回到已打开目录 | 原查询、位置、分组和 Host 筛选仍在本次应用运行。已打开历史按当前真实 Tab 更新，不依赖目录模拟状态。 |

860×580 首个试验保留 Vault 的完整标题和已完成扫描条，结果只露出首行的上半部。短窗改用紧凑标题，扫描进行时显示进度；并存的范围和跳过提示可由「扫描提示」展开，阻断性错误留在原处。侧栏进入历史视图时挂载 Vault。源码主入口为 `SidebarSessionIndex.tsx`、`AiVaultPanel.tsx`、`ai-vault-session-filters.ts` 和 `AiVaultScanIssueBanners.tsx`。继续沿用 Vault 的恢复授权和绑定。 [短窗试验](evidence/iteration-18-20-shape/i18-history-mode.png)

## 验收范围

从既有双 Pane 场景回到工作台，使用真实 Vault 扫描一次性 Codex 历史记录。验证打开中的记录不在此视图，选择明确续接动作后实际聊天显示原记录，只新增一个 native Tab，返回后原目录条件仍在。删除、关闭、启动真实模型、无已知工作树的重新归属、直接将恢复目标编入 Workspace 按各自场景独立验收。

英语浅色与简中深色的 860×580 回放均验证恢复菜单在结果区可点击。两种语言的实际历史续接与输入焦点见截图和断言。 [简中历史](evidence/iteration-18-windows-zh/i18-history-mode.png) · [实际续接](evidence/iteration-18-windows-zh/i18-native-resume.png) · [交接过程](evidence/iteration-18-windows/unopened-to-chat/timeline.json)

最终回放的扫描未出现叠加提示。提示折叠已有实现，须用同时产生 WSL 访问提示和跳过记录的档案核对展开、收起与结果焦点。 [中间版本观察](evidence/iteration-18-20-shape/i18-stacked-scan-notices.jpg)
