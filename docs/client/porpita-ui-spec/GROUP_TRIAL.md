# 顶层 Tab Group：等条件组件试验

第七轮在现有 Worktree 内容层验证分隔线焦点、调节和取消。第十轮将本页选定的一行 Group Selector 接入使用真实本地会话的 Electron 开发预览。夹具保留 240/420/920 CSS px、12 个组及指针拖放证据，开发预览补充真实标题栏的系统控件、菜单移组和全组查找。 [第七轮](ITERATION_07.md) · [第十轮](ITERATION_10.md)

第十四轮接入真实标题栏拖放。松手打开目的组菜单；Escape 归还源标签焦点，确认后沿用原移动规则与源组回退。 [第十四轮](ITERATION_14.md)

## 第二轮 Group Selector

继续采用一行 **Group Selector + 当前组 Tabs + 打开列表**。选择器保留组图标、完整可访问名称与展开指示，文字在 132 CSS px 和可用区域 31% 两者中较小的宽度内截断。打开菜单显示全名和选中组。只有一个组时依然可访问组操作，紧凑状态保留创建和打开列表。小于 260 CSS px 时沿用 Orca 隐藏横滚箭头的规则，由打开列表补足；标题栏的系统控件保有自己的空间。可用宽度取窗口保留区域后的标题栏容器。

| 标题栏可用宽度 | 活跃组 Tab / 全部组 | 选择器 | 可见标签条 | 实际活跃 Tab 可见宽度 |
| --- | ---: | ---: | ---: | ---: |
| 240 CSS px | 1 / 1 | 74px | 93px | 94px |
| 420 CSS px | 8 / 4 | 130px | 169px | 144px |
| 920 CSS px | 30 / 12 | 132px | 667px | 144px |
| 240 CSS px | 30 / 12 | 74px | 93px | 94px |

在原 Orca 标签条上实际测得上述值，长 CJK/Latin 标题及组名共用同一组数据。240px 时首个标题仍截断，打开列表负责完整名称和查找。试验确认滚动菜单可选择超出视口的 Tab。生产使用列表数据较大时，复用现有 Command/RecentTabSwitcher 按组搜索，并优先展示最近和固定对象。宽窗沿用同一模式，现有试验支持减少常驻组名占位。

- Tab 将焦点移到组选择器。Enter、Space 或方向键开菜单，方向键及 Home/End 移动，Enter 确认，Escape 归还选择器焦点。切组激活该组最近仍打开的对象。菜单焦点与活跃对象选中态分别表达。
- 拖动顶层 Tab 到组选择器时高亮投放目标，松手后显示目的组。可用「移至组」走同一选择菜单。目标组提交时保存原对象 ID、固定标记和状态，追加到目标组常规位置，源组激活最近剩余对象。先留在源组，用户明确切组才导航。取消、同组或非法目标均保持原归属。
- 打开列表支持跳到任一组。命中后激活对象并把 Tab 滚入可见位置；夹具用 Tab 条的原生横滚定位第 30 项。真实产品的搜索、固定、重命名、删组迁回 General、重启恢复、系统控制命中和读屏仍按 J03/J06/J13。

用实际 Playwright 键盘和指针验证了切组及 MRU、长名、12 个分组、窄态第 30 项定位、拖放取消与目标确认、键盘移动。第二轮保留浅深色各四个规格图。读屏与系统标题栏由 Electron 集成验证。 [测量与操作](evidence/group-shape/interaction.json) · [240px 深色](evidence/group-shape/tab-bar__PorpitaGroupSelectorShape--compactDense.dark.png) · [420px 浅色](evidence/group-shape/tab-bar__PorpitaGroupSelectorShape--compact.light.png) · [投放后的目标菜单](evidence/group-shape/drop-destination.png) · [夹具](tools/PorpitaGroupSelectorShape.fixture.tsx)。

复现时将该夹具复制到 Porpita 隔离树的 `src/renderer/src/components/tab-bar/`。用该树的 `node config/scripts/component-fixtures/fixtures-shot.mjs tab-bar/PorpitaGroupSelectorShape --theme both --out <目录>` 启动并渲染，随后从 SPEC 目录运行 `node tools/replay-group-shape.cjs <Porpita 树> <目录>`。最后用 `fixtures-shot.mjs --stop` 停止该隔离服务并移除复制件。

## 首轮 Group Selector 与 Inline Group Names

**问题**：组入口在一行标题栏里占用多少空间，窄窗是否仍能识别当前对象。此试验用当前 Porpita HEAD 的 `TabBar`、`Button`、`DropdownMenu`、tokens 与内置 fixture renderer；两候选用同一 4 组/12 对象数据、同一初始组和同一标签条。420px 和 920px 是给标题栏工作对象分配的区域宽度，非整窗宽。使用已有 TerminalTab 仅作为 fixture 标签载体；工作对象图标、保存、真实 Session 和跨 Host 都没有在这里实现。

| 对照 | A：组选择器 + 当前组 Tabs | B：组名内联 + 当前组 Tabs |
| --- | --- | --- |
| 紧凑，浅色 | [420px](evidence/group-trial/tab-bar__PorpitaTopLevelGroupResearch--selectorNarrow.light.png) | [420px](evidence/group-trial/tab-bar__PorpitaTopLevelGroupResearch--stripNarrow.light.png) |
| 宽，深色 | [920px](evidence/group-trial/tab-bar__PorpitaTopLevelGroupResearch--selectorWide.dark.png) | [920px](evidence/group-trial/tab-bar__PorpitaTopLevelGroupResearch--stripWide.dark.png) |
| 选择事件 | [激活 Remote lab 后](evidence/group-trial/tab-bar__PorpitaTopLevelGroupResearch--selectorKeyboard.light.png) | 内联按钮用于同一组切换；本次只有静态对照 |

观察：在 420px，A 留下约 230px 标题视区，能辨认 `Root Session…`，并看见下一项；B 的四个常驻组名先占走约 240px，当前标题只剩 `Root S…`、边缘渐隐更早。两者都保留成熟标签条的选中线、箭头与创建区。920px 时 B 使组一眼可见，仍缩短各对象名称；A 给任务对象更多空间，切到其他组则多一步。A 的交互夹具用焦点事件打开原 DropdownMenu 并选择 Remote lab，观察到相同组件更新当前组和标签；这是事件与呈现试验，实际键盘上下键/Enter、屏幕阅读和平台标题栏焦点留待集成回放。

**推荐**：默认一行组选择器 + 当前组 Tabs，保持横向 overflow 与可全组搜索的最近列表。宽窗暂不承诺单独模式；组名内联可作为以后确有跨组工作需求时的比较方向。试验里的 B 只检验常驻组名的空间代价；没有实现所有组内容都铺开的可折叠条。后者至少同样消耗组标题宽度，其交互仍待验证。

[420px 对照原图合页](evidence/group-trial/compact-comparison.png)

[夹具源码](tools/PorpitaTopLevelGroupResearch.fixture.tsx) 是可审查的技术试验。已渲染浅深色共 10 张。目标顶层 Tab 的拖放、固定、删除组回迁、恢复、实际窗口 600/820/1280px、1/8/30 对象以及同一 Native Session 的唯一归属按 J03/J04/J06/J13 验收。夹具的实验选择未写入产品源码，也不代表已批准的目标设计。
