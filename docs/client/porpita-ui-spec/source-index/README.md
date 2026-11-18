# 桌面 UI 源码发现索引

此索引由当前 Porpita 源树解析，目的是从实现反查界面覆盖；不是路由列表或已验收界面统计。

- [renderer.jsonl](renderer.jsonl)：每行一个渲染/动效候选源文件，包含桌面/辅助入口的静态可达性、JSX、交互元素行号、事件/标签、条件谓词、动效 class。相同组件可被多个界面引用，非可达或非可见项保留待归并。
- [styles-motion.jsonl](styles-motion.jsonl)：10 个 CSS 样式文件里的 keyframes、animation、transition 与减少动态规则，标注行号。动态动画、库动画与 OS 行为继续从调用点和实际回放发现。
- [native-host-candidates.jsonl](native-host-candidates.jsonl)：独立窗口、通知、托盘、原生菜单、打开/保存/消息框调用候选；其中含环境探针及后台或条件分支。
- [native-host-coverage.csv](native-host-coverage.csv)：82 个调用点归到实际窗口、对话框、通知与已知测试宿主，保留源码行和可追踪条目。运行资格按对应回放。
- [summary.json](summary.json)：入口、Active View、根 overlay、右 Dock 与 Settings 声明；重复调用与条件分支保留原位置。
- [module-coverage.csv](module-coverage.csv)：每个候选模块的功能域归属和映射质量，用于发现分类之外的真实对象；仅特定锚点明确绑定到矩阵行。
- [primitive-usage.csv](primitive-usage.csv)：静态解析的共享组件导入与 JSX 调用位置，带源行、组件规则 ID、功能域映射与事件。转导出、原生和非 JSX 控件继续按渲染索引核对；用例存在不代表已被观察。

方法：组合应用主入口、Popout、Space、Web 关联入口；React 静态 import/dynamic import、页面注册、设置深链接、UI JSX 事件、原生 Electron 主进程源、CSS 和回放互相核对。Web 独立页面不是桌面内页面，静态共享模块同时出现在两条路径很常见。目录存在、静态可达、打包进入与用户能够到达是不同事实；对门控、跨端、第三方内容、运行数据须用注册表、调用点和实测再确认。用 `rg -n` 或按行读取解析定位，新增的设计条目归入同一 Inventory ID。
