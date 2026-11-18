# 第 48 轮 · Space 清理失败的行内原因

第 47 轮实况中，失败行把工作树、分支名和 Git 的长诊断挤在同一行。简中用户看到红色路径开头，要等瞬时提示或查看完整文字才能确定 Git 拒绝了什么。 [第 47 轮画面](evidence/iteration-45-47-space-cleanup-zh/i47-space-partial.jpg)

- 名称和分支仍在第一行，失败原因放在其下方。失败文字可换行，图标和符合当前条件的「强制」操作保留。工作树的列、行焦点及键盘动作沿用 Space。
- 原因取自当前删除状态。已分类原因包括未提交改动、Git 锁、孤立目录、登记缺失和子模块。终端与 Agent 会话各自区分仍在运行和退出待确认。遇到未分类的错误显示「清理受阻」，原有诊断保留在悬停详情和错误提示中。
- 主窗口再次发布状态后，Space 仍保留本次删除错误。原有行内重试权限和刷新后审阅的顺序沿用第 47 轮。
- 批次实际移除数为零时，结果栏显示「本次未删除工作区」，具体原因留在对应行。

对应 M.02.07。复用 `workspace-space-worktree-row.tsx` 与 `worktree-delete-error-display.ts`。失败行随结果加入原列表，无独立进出动画。运行采用 Windows Space 的 760×700 内容视口。审阅打开后写入临时文件，让 Git 拒绝普通删除。再次接收主窗口发布后，核对原行可读文字、完整诊断和仍存在的文件。其他拒绝分类由源码覆盖，需在能触发各门禁的环境复验。 [简中实况](evidence/iteration-48-50-space-zh/i48-space-refusal-reason.jpg) · [英语实况](evidence/iteration-48-50-space-en/i48-space-refusal-reason.jpg)
