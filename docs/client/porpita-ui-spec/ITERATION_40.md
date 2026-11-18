# 第 40 轮 · 本机 PTY 的绑定状态与刷新

本机 PTY 列表原有绑定、未绑定和等待态。恢复期间的列表可能仍有旧 tabId，诊断读取失败后也会保留上次观察。定位按钮由已确认的绑定和本次读取状态共同决定。

| 状态 | 呈现与操作 |
| --- | --- |
| 绑定明确 | 使用原箭头和可访问名称，继续该终端。 |
| 绑定待确认 | 行内显示「正在检查标签页…」。 |
| 无标签页 | 显示「无标签页」，保留原进程和观察详情。 |
| 刷新失败 | 保留上次观察，顶部显示既有失败提示和「重试」。读取恢复后重新显示当前可用的定位入口。 |
| 正在结束 | 延续结束进度，暂停该行的定位操作。 |

复用原分组、Collapsible 和虚拟列表。长标题保留截断和可访问名称。减少动态时，详情箭头直接切换方向。终止授权仍由已有 owner 和 incarnation 来源判断。

源码映射 A.03.16。涉及 `ResourcePtyRow.tsx`、`ResourcePtyPanel.tsx`、`resource-pty-view-model.ts` 和 `resource-session-inventory-cache.ts`。回放使用实际 PTY 和本次创建的无标签进程，注入一次诊断读取失败以验证旧样本与重试。 [简中连续回放](evidence/iteration-39-41-resource-continuity-zh/local-pty-availability/timeline.json)
