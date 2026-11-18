# Codex UI SPEC 使用说明

本目录是 Porpita Workspace / Tab / SidePanel 的结论参考资料包，不是开发执行包。

请按以下顺序使用：
1. 阅读 `README.md`、`01-foundation/` 与 `DECISIONS_AND_OPEN_QUESTIONS.md`，理解已确定的产品边界。
2. 阅读 `03-orca-source-mapping/ORCA_CURRENT_IMPLEMENTATION.md`，在本地重新核对当前 Porpita 分支和 Orca 上游源码是否仍匹配参考提交。
3. 按 `04-ui-spec-process/UI_SPEC_BRIEF_AND_ACCEPTANCE.md` 开展真实 UI SPEC：观察、交互回放、shape、迭代和体验验收。
4. 对 `Open` 项给出基于真实源码和运行体验的最终推荐；对 `Confirmed` 项不要无依据地重新开放。
5. 产出该文件所列 UI SPEC 交付物。此阶段先不大规模改代码；待用户确认 SPEC 后，再拆分 UI 实施阶段。

约束：不要将 Orca Worktree 直接等同 Porpita Workspace；不要将 Activity Thread 等同 Native Session；不要将 RightSidebar 视为已经具备通用 Standalone/Embedded Panel Host；不要为展示 ACS 内部对象而重构整个 Orca 信息架构。
