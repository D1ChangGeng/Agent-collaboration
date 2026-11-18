# Porpita Workspace UI/UX Reference Pack v1.0.0

用途：为下一轮 Codex UI SPEC 流程提供已收敛的产品结论、信息架构基线、交互原则、Orca 源码映射和待研究问题。它是参考资料包，不是实现开发包，不要求 Codex 直接按本文改代码。

目标：在最大程度继承 Orca 成熟 UI/UX 的前提下，逐步形成 Porpita 自己的 Session Index、Workspace、Top-level Tab、Tab Group 与 SidePanel 组织体验。先由 Codex 对真实产品行为进行 UI SPEC 调研、shape、播放/回放验收和迭代，再据此形成分轮 SPEC。

## 文件导航
- `01-foundation/PRODUCT_AND_IA_BASELINE.md`：产品定位、核心对象、关系和已确定原则。
- `01-foundation/DOMAIN_RELATIONSHIPS.md`：Session、Project、Route、Identity、Harness、Machine、Conversation、Workspace、SidePanel 的概念关系。
- `02-interaction-model/WORKSPACE_AND_PANE.md`：Workspace、Pane、布局、焦点、Session 加入/移除。
- `02-interaction-model/TOP_LEVEL_TABS_AND_GROUPS.md`：顶层 Tab 与 Tab Group 的结论和待确认交互。
- `02-interaction-model/SIDEPANEL_MODEL.md`：SidePanel Definition / Instance、独立与嵌入两种呈现。
- `02-interaction-model/SESSION_INDEX_AND_NAVIGATION.md`：Sidebar / Session Index 与 Workspace 的衔接。
- `03-orca-source-mapping/ORCA_CURRENT_IMPLEMENTATION.md`：已核对的 Orca/Porpita 源码现状、可复用机制和真实差异。
- `04-ui-spec-process/UI_SPEC_BRIEF_AND_ACCEPTANCE.md`：给 Codex UI SPEC 的研究任务、场景、交付物和验收原则。
- `DECISIONS_AND_OPEN_QUESTIONS.md`：决策状态，区分已确定、推荐、待研究。
- `DECISION_LOG.md`：核心决策理由。
- `SOURCE_BASELINE.json`：参考仓库、提交与源码路径。

## 使用方式
把整个目录交给 Codex，要求它先读取本参考包，再基于当前 Porpita 本地源码和固定 Orca 上游基线开展 UI SPEC。Codex 的职责是验证真实 UI 行为、补足视觉和交互细节、制作场景回放并形成分轮 SPEC，不是重新发明产品定位或擅自改变已确定的对象边界。

本包不授权直接进入大规模 UI 实现。先完成 UI SPEC 与体验验收，待用户确认后再进入逐步实现。

## 重要限制
1. “已核对”指本轮读取源码确认，不等于已在运行时完成全部交互验证。
2. `Workspace` 指 Porpita 用户工作空间，不等于 Orca 既有 Worktree/Workspace。
3. Orca 当前 Titlebar tabs、per-worktree unified tabs、Pane groups、App Shell RightSidebar 并非本包定义的全部顶层工作对象模型。
4. `Native Session` 与 `ACS Conversation` 是不同实体。
5. Session、SidePanel 被组合进 Workspace，不改变它们原本的身份、权限或生命周期。
6. 本包只记录 UI/UX 结论和 UI SPEC 研究边界，不包含新的 ACS Core 协议或数据库实现要求。
