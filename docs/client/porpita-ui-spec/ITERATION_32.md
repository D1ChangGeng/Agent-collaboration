# 第 32 轮 · 资源管理器的本机汇总与 PTY

用户在同一窗口切换 Host 时仍可能需要检查桌面机器上的负载。当前资源汇总来自桌面原生快照。项目树还会展示可用的配对 Runtime 项目，PTY 页则使用本机守护进程的会话清单。

采用 Orca 的资源管理器弹层、CPU 与内存汇总、资源树和标签页。预览的入口为内存明确标出本机范围。汇总区保留「本机汇总」标签，PTY 页签显示「本机 PTY」。保留通用的「资源管理器」标题，让项目树里的远端条目继续具有自己的来源。对照过随当前 Chat 切换整个资源面板的方案，原资源和守护进程各有独立用途，选择保持独立。

Windows 隐藏回放验证未采样时的范围标签、600×460 窄窗、Local 与 Studio 切换，以及本机 PTY 标签。另用标明的本机资源样本验证数字和版面。前台原生采样与真实远端资源负载另行验收。主要源码为 `ResourceUsageStatusSegment.tsx`、`resource-usage-popover-summary.tsx` 与现有资源采集控制器。对应 A.03.08、A.03.01 与 J13。

最终回放在两个固定 Explorer 分别选中时打开资源管理器，核对本机汇总与本机 PTY。截图的 12% CPU、320 MB 工作集和 440 MB 私有提交内存是版面样本。 [切换连续帧](evidence/iteration-30-32-ports/local-resource-scope/timeline.json) · [窄窗样本](evidence/iteration-30-32-ports/i32-resource-scope.png)
