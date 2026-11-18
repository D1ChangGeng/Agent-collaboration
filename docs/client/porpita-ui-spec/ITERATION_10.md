# 第十轮 · 顶层分组与打开列表

在第九轮布局对象上接入已通过夹具比较的 Group Selector。用户整理顶层 Workspace 和独立工具，能在窄窗找到另一组或已关闭的呈现。会话 Pane 和 Explorer 内部状态由各自的宿主继续维护。

## 设计与试验边界

第二轮夹具在 420px 以单行选择器保留更多活动标签。将相同宽度原则带到真实 Electron 标题栏，和 138px 自绘系统按钮空间同时检查。Chromium 标签组的讨论为显式移动和重新打开提供语义参照。选用 Orca 原标题栏色、标签激活线、原生菜单与命令列表，保留单行与横向溢出。 [分组对照](GROUP_TRIAL.md) · [Chrome 标签页与标签组](https://support.google.com/chrome/answer/2391819)

- 组名触发器保留完整可访问名称，排布上限取 132px 和可用条宽的 31%。当前组显示可见的顶层对象。打开列表跨组查找，已关闭条目附状态并可以恢复。
- 新建组使用现有 Group Name Dialog。通过右键或键盘上下文菜单选择目的组。提交只修改对象所属组，源组留在最近的剩余对象。切入目的组恢复其中最近对象。组切换复用 Radix 子菜单与单选菜单的键盘行为。
- 窗口缩到 600 CSS px 后，打开列表仍可操作，系统留白按已有 CSS 变量占位。重新进入预览恢复上次选择和布局。Ctrl+Tab 仍由当前 Orca 内容快捷键负责。拖放、固定、重命名、删组迁移、系统读屏和不同 DPI 分别按正式集成验证。目前布局记录仅保存于预览档案。

主要源码为 `WorkspacePreviewTabs.tsx`、`workspace-preview-model.ts`、`ProjectGroupNameDialog.tsx`、`WindowControls.tsx` 和 `app-window-chrome.ts`。关联 D.08、R.07、T.05 及 J03/J06/J13。

## 验收

使用原生会话建立多个顶层 Workspace，加入一个长中英混合组名。记录源组回退、进入新组、窄窗跨组查找、标题栏命中范围和重载恢复。

Windows 600×460 CSS px 使用跨组查询来回切换。恢复时先处理现有产品的启动提示，再从「工作空间（预览）」进入，读取上一次活动组和布局。此回放覆盖 renderer 重载。完整进程重启和正式 profile 落盘需独立验证。 [窄窗回放](evidence/iteration-09-11-windows/find-hidden-work/timeline.json) · [系统按钮坐标](evidence/iteration-09-11-windows/group-geometry.json) · [重载后恢复](evidence/iteration-09-11-windows/i10-layout-restore.png)
