# Decision Log

- **D-001 Session 是直接工作对象**：用户进入具体 Harness Session；Identity 和 Project 是关联维度。
- **D-002 Workspace 是用户拥有的布局上下文**：组合 Session 与 SidePanel，不等于 Project。
- **D-003 Top-level Tab 表示顶层工作对象**：Workspace 或 Standalone SidePanel，避免 Session 数量膨胀顶层标签栏。
- **D-004 SidePanel 保留独立语义**：可独立打开或嵌入 Workspace，不是 Session。
- **D-005 三层 Tab 分开管理**：Top-level Tab、Workspace Pane 内容、SidePanel Internal Tab 的所有者不同。
- **D-006 复用 Orca 布局原语**：优先复用 Pane Tree、Split、drag/drop、focus、persistence。
- **D-007 Orca Worktree 不等于 Porpita Workspace**：Worktree 是代码/执行环境范围；Porpita Workspace 是用户布局。
- **D-008 Activity Thread 不等于 Native Session**：Agents Activity 是活动/导航视图，不是完整 Session 目录。
- **D-009 Panel Scope 显式化**：SidePanel 上下文由自身 Scope 决定，不默认跟随焦点 Session。
