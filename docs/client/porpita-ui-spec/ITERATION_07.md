# 第七轮 · 现有分屏的调节与取消

用户用现有内容标签菜单把两个工作对象排到不同 Pane。使用同一条分隔线调整空间，键盘可操作，拖动后可以取消并回到调整之前。它对应 Orca Worktree 的内容分屏，为 Porpita Workspace 后续复用 Pane tree、比例和焦点规则提供实际依据。

## 设计决定与实现

第二轮发现两侧栏并存会挤压终端，已补主区域空间预算。既有内容分屏能用指针调节。分隔线缺少可聚焦的调节入口，指针取消会保存预览值。对照方案包括全局方向键切组或将调整放入组菜单。前者会与终端及现有键位交叠，后者适合离散布局操作。采用可聚焦的原分隔线，参照 WAI-ARIA APG 的可调 Separator，保留 Orca 的分隔线尺寸、hover 反馈和现有布局 owner。 [第二轮](ITERATION_02.md) · [WAI-ARIA Window Splitter](https://www.w3.org/WAI/ARIA/apg/patterns/windowsplitter/) · [VS Code 分屏与组](https://code.visualstudio.com/docs/agents/run/agents-window-configuration#arrange-chat-tabs-and-groups)

- Tab 可到达可见分隔线。左右分屏用左右键，上下分屏用上下键。每次移动 5 个百分点，Home/End 抵达原约束 15% 和 85%。修饰键、IME 与其他内容快捷键继续交给原处理路径。
- 可访问名称、方向和比例通过 separator 暴露。分隔线命中区为 6 CSS px，可见线为 3 CSS px。聚焦采用现有 ring 色与分隔线选中色，颜色切换为 100ms ease，减少动态时立即切换。浏览器内停靠 DevTools 共用分隔组件并提供自己的名称。
- 拖动直接预览 Pane 宽高，释放后经现有 owner 保存。Escape 和 pointercancel 回到手势起点比例。意外失捕沿用现有收尾逻辑。调节期间各 Pane 的内容、标签与归属保持。
- 现有相对比例上下限在极窄窗口仍允许把一侧压得很小。跨 Host Workspace 的最小内容宽高与单 Pane 聚焦呈现由独立工作区模型决定。

主要入口为 `TabGroupSplitNodeTree.tsx`、`TabWorkspaceLayoutMenuSection.tsx`、`tabs-split-ratio-actions.ts` 与 `tab-group-layout-owner-commands.ts`。 [顶层 Group Selector 设计试验](GROUP_TRIAL.md)

## 验收

Windows 英语浅色与简中深色各通过四步。通过真实菜单创建两个终端，移一个到右侧内容分屏。两次方向键从 50% 到 60%，标签身份和活跃组保持。拖动预览后按 Escape，边界回到已提交的 60%。820×520 CSS px 减少动态条件验证上下限和可见焦点。上下分屏、停靠 DevTools、pointercancel、重启恢复与系统辅助技术保留在待验范围。 [英语](evidence/iteration-07-windows/run.json) · [简中](evidence/iteration-07-windows-zh/run.json) · [拖动与撤销](evidence/iteration-07-windows-zh/cancel-split-resize/timeline.json)

运行 `node tools/observe-installed.cjs <输出目录> --related-split`，依第五轮设置隔离开发构建。真实鼠标与键盘动作在后台 Electron 的 CDP 窗口内执行。
