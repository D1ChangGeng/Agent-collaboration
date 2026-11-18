# 第八轮 · Explorer 回到原查找

使用文件名筛选后切到历史面板或另一工作树，再回到原 Explorer 时，用户可以从原查询继续。范围绑定实际文件操作 owner、工作树和显示根。相邻工作树仍可各自查找。

## 设计决定与实现

基线在同一个项目从 Explorer 切到 Vault 再回来时，文件名筛选被清空。Explorer 已有 Names/Contents 视图、目录选择与相应的实际读取路径。可复用的设计是保存搜索意图，并在返回时通过当前 owner 重新取得结果。维持隐藏树实例也能保存输入，但会延长 watcher、列表缓存与模态交互的生命周期。将小范围输入交给 Renderer 现有 Explorer 状态，保留正常卸载并按当前归属重新列目录，能支持同一需求。VS Code 对 Explorer 自动跟随提供开关，说明显式查看位置和随焦点切换是不同的操作。 [VS Code Explorer 显式定位](https://code.visualstudio.com/updates/vApril)

- 用户侧沿用现有 Explorer 的 Names 输入和清除按钮。切换工具和返回同一范围时恢复输入。另一工作树或根使用自己的值。配对 Host 身份进入范围键，代次变化使用新查询范围。
- 当前实现保存在本渲染会话内曾编辑的最近 128 个非空范围。文件结果仍由当前 owner 回答。显式揭示路径可清除当前名称筛选。Contents 模式沿用原查询和结果流程。
- Dock 因窄窗暂时收起时停止文件名列表读取，重新显示时根据当前归属恢复。选择节点、展开树和定位指令沿用既有职责。

主要入口为 `FileExplorer.tsx`、`use-file-explorer-name-filter.ts`、`explorer-dir-state.ts` 和 `use-file-explorer-tree-load-effects.ts`。

## 验收

1. 在本地 Git 项目筛选 `release-checklist`，切到 Vault 再回 Explorer，查询与实际文件仍可用。
2. 给两条不同工作树输入不同筛选，往返后恢复各自值。验证原工作树双击结果仍打开对应文件。
3. 在 820px 窄窗与减少动态条件检查显示。用回归用例核对查询按范围保留、旧结果异步到达和视图重挂。

Windows 英语浅色与简中深色各通过五步。基线证实切换工具后输入清空，改造后从目录项目返回 Git 工作树恢复查询，在 820×540 CSS px 下双击打开原文件。验证工具仅为系统选择目录对话框提供预设路径。 [基线](evidence/iteration-08-baseline/run.json) · [英语](evidence/iteration-08-windows/run.json) · [简中](evidence/iteration-08-windows-zh/run.json)

运行 `node tools/observe-installed.cjs <输出目录> --related-explorer`。添加 `--related-baseline` 时使用前一构建检查查询清空。所有试验文件和工作树均由隔离档案创建。

后续 Standalone/Embedded Explorer 仍需显式的实例 ID、Host/根验证、展开、键盘选择和滚动位置迁移。 [SidePanel 能力矩阵](SIDEPANEL_CAPABILITY_MATRIX.md)
