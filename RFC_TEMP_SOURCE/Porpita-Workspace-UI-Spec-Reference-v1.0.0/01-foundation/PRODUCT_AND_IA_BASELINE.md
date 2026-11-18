# 产品定位与信息架构基线

## 产品定位
Porpita 是以 Agent 工作和跨 Harness 协作为核心的独立桌面开发应用。它继承 Orca 成熟的桌面工作台、Native Chat、工具调用、Diff、审批、终端、Worktree 和插件能力，同时由 ACS Core 提供跨 Harness 身份、通信、项目协作与通信客户端服务。用户看到的首先应是一款自然、完整的 Agent 开发桌面应用，而不是 ACS 技术管理控制台。

## 核心体验原则
1. **Chat-first**：Native Session 是用户直接进入、观察和操作的主要工作现场。
2. **Session-centric**：Session 是会话导航和直接访问的基本对象。
3. **Workspace-oriented**：Workspace 是用户将多个工作对象组织成一个工作上下文的方式。
4. **Multi-surface**：Workspace 可组合多个 Session 与独立 SidePanel；SidePanel 也可独立打开。
5. **Harness-agnostic at product level**：Harness 是 Session 的运行环境属性，不应成为访问 Session 的必要中间层。
6. **Preserve Orca**：优先继承 Orca 已有布局、组件、交互和原生执行能力；只扩展实际缺少的能力。
7. **Hide implementation concepts**：Project、Route、Identity、AgentSlot 不应机械映射成 UI 层级，通过关联信息、分组、筛选和上下文体现。
8. **User-owned organization**：系统提供合理默认值，但不持续覆盖用户显式组织。

## 四层 UI 信息架构
### A. Top-level Navigation
管理当前打开的顶层工作对象：Workspace Tab、Standalone SidePanel Tab、Tab Groups。
### B. Workspace Composition
一个 Workspace 由一个或多个区域组成。区域可以承载 Native Session 或 SidePanel Instance，通过 Pane / Split / Layout 组合。Workspace 保存布局、焦点和用户呈现状态。
### C. Work Surfaces
Native Session 保留完整 Harness 原生体验；SidePanel 保留自身功能、上下文与内部导航。
### D. Session Index / Sidebar
发现、搜索、筛选、分组和访问所有可用 Native Session；可将 Session 打开到当前 Workspace、指定 Pane 或新 Workspace。

## 不应混淆的对象
- Project：长期协作范围。
- Route：Project 内开发/协作路线。
- Identity：稳定通信主体。
- Role：主体在特定协作范围内承担的职责。
- AgentSlot：ACS 内部绑定/权限地址，不是用户导航实体。
- Harness：原生运行环境。
- Machine / Host：运行位置。
- Native Session：Harness 中真实存在的会话。
- ACS Conversation：通信参与者之间的消息关系与历史。
- Workspace：用户工作对象组合及布局。
- SidePanel Definition：面板功能类型。
- SidePanel Instance：某次实际打开、具有上下文和内部状态的面板实例。
- Top-level Tab：Workspace 或独立 SidePanel 的导航入口。
- Tab Group：顶层工作对象的用户组织容器。

## 初代体验范围
优先明确 Native Session 统一目录和唯一标识、Workspace 作为顶层工作对象、Workspace 内多个 Session 的 Pane/Split/Focus、SidePanel 独立打开与嵌入、顶层 Tab/Tab Group、Sidebar 与 Workspace 的自然衔接、Orca 原生体验保留边界。不把所有 ACS 内部对象可视化，不将 Workspace 设计成任务看板。
