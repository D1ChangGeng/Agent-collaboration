# UI Inventory

当前覆盖模型：20 个功能域，371 个设计条目。现有界面与待新增对象分开标注；组件族按实际用途合并。每条现状、范围、状态和回放证据见 [Coverage Matrix](COVERAGE_MATRIX.md)。

来源：实际 Porpita 应用、入口与深链接、静态渲染/事件索引和原生 Electron surfaces；以 [源索引](source-index/README.md) 继续反查遗漏。

## A · 桌面外壳

- `A.01` 主窗口、系统菜单与缩放
- `A.02` 标题栏与区域宽度
- `A.03` 状态栏
  - `A.03.01` 账号、配额、进程、空间与端口弹层
  - `A.03.02` 状态栏可见项与插件贡献
  - `A.03.03` 混合 Workspace 的用量归属
  - `A.03.04` 用量入口、Host 账户与原编辑器交接
  - `A.03.05` 用量读取、断线和配对撤回
  - `A.03.06` 当前工作对象的端口查看与回源
  - `A.03.07` 端口等待、断线和恢复
  - `A.03.08` 资源面板的本机汇总与 PTY
  - `A.03.09` 工作树端口详情及 Host
  - `A.03.10` 本机端口到应用内 Browser
  - `A.03.11` 从资源表行定位实际工作树
  - `A.03.12` 端口详情的监听地址与 Browser 目标
  - `A.03.13` 刷新已变化的本机监听
  - `A.03.14` 从资源表继续现有 Browser 标签
  - `A.03.15` 从资源表和本机 PTY 定位原终端窗格
  - `A.03.16` 本机 PTY 的绑定状态与刷新恢复
  - `A.03.17` 本机 PTY 的批量选择范围
- `A.04` 首页、无工作区与启动错误
- `A.05` 启动载入、重连、关闭、恢复
- `A.06` 平台窗口变体

## B · 入门、许可与教育

- `B.01` 语言与工作方式选择
- `B.02` Agent、权限与 Windows Terminal
- `B.03` 主题、通知、集成步骤
- `B.04` 向导进度、返回、稍后设置
- `B.05` 引导浮层、帮助、特性墙
- `B.06` 首次隐私提示与反馈

## C · Sidebar、项目与发现

- `C.01` 导航、项目头和搜索
- `C.02` 项目、Host 和仓库接入
- `C.03` Host 选择、SSH/WSL、远程文件浏览
- `C.04` 工作树行、分组、筛选、拖排
  - `C.04.01` 工作树图标、名称与 Emoji
- `C.05` 新建执行工作区
  - `C.05.01` 创建步骤、Terminal 与 Chat 占位
  - `C.05.02` Sparse checkout、目录与预设
- `C.06` 工作树元数据、休眠、删除、清理
- `C.07` Activity、线程揭示与关注
- `C.08` 工作区看板、筛选与批量选择
- `C.09` 工作对象搜索与 Quick Open
  - `C.09.01` 跳转筛选器与实时提示
- `C.10` Session Index 列表、筛选与打开（目标新增）
  - `C.10.01` 从跳转面板转交会话历史
  - `C.10.02` 从已打开聊天定位到所属 Workspace
  - `C.10.03` 侧栏会话目录与原位打开（目标新增）
  - `C.10.04` 会话位置筛选、项目分组与短窗（目标新增）
  - `C.10.05` 会话目录交接 Vault 与返回原 Workspace
  - `C.10.06` 未打开历史的查找、续接与原目录返回（目标新增）
  - `C.10.07` 目录中的 Native Chat 运行与待输入状态（目标新增）
  - `C.10.08` 从目录参照项目协作连接与消息状态
  - `C.10.09` 已开 Chat 的 Host 来源、筛选、失联与恢复（目标新增）

## D · 工作台、Pane 与分屏

- `D.01` 现有内容 Tab 条、溢出和创建器
- `D.02` 单组/多组、激活、上下文菜单
- `D.03` 分屏树、拖放和调宽
  - `D.03.01` 分隔线键盘调节与撤销
- `D.04` Pane 焦点、最大化与恢复
- `D.05` 关闭、停放、未保存确认
- `D.06` 浮动工作区、独立 Terminal
  - `D.06.01` 浮动工作区调宽／高和退出
- `D.07` Porpita Workspace 生命周期（目标新增）
  - `D.07.01` 本地双会话布局、窄窗切换与还原（目标新增）
  - `D.07.02` 桌面档案布局与冷启动恢复（目标新增）
  - `D.07.03` 跨 Host 的已开会话组合与窗格切换（目标新增）
  - `D.07.04` 来源限定布局档案与混合 Workspace 冷恢复
  - `D.07.05` 混合 Workspace 中单侧失联、重连与移除（目标新增）
- `D.08` Top-level Tab 和 Tab Group（目标新增）
  - `D.08.01` 标题栏组选择与跨组打开（目标新增）
  - `D.08.02` 顶层 Tab 拖到组选择器与撤销（目标新增）

## E · Native Chat

- `E.01` 空白、启动、恢复、不可用
- `E.02` Pane Header、模型与权限
- `E.03` Composer 输入与模式
- `E.04` Composer 工作台、命令、模式和草稿
- `E.05` 附件、拖入、粘贴、引用
- `E.06` Transcript、Markdown、流式与滚动
- `E.07` 消息动作、引用与媒体
- `E.08` 工具、Diff、子 Agent 与反馈
- `E.09` 审批、问题、信任、授权请求
- `E.10` 队列、运行结束与恢复

## F · Terminal、Harness 与浮动运行

- `F.01` 终端标题、布局、分割和视图
- `F.02` Shell 输入、链接、查找、复制
- `F.03` 快捷命令、Agent picker、Shell 安装
- `F.04` 运行状态、停放、复连、退出
- `F.05` 远程输入/驱动、模拟器和独立模式

## G · RightSidebar 与 SidePanel

- `G.01` Dock、Activity Bar、调宽与隐藏
- `G.02` Explorer 文件树和工作区根
  - `G.02.01` 名称过滤、内容搜索与结果
  - `G.02.02` 文件名筛选按 owner、工作树和根恢复
- `G.03` Source Control、提交、历史与分支
  - `G.03.01` 暂存、撤销、提交与同步
- `G.04` Checks 和检查详情
- `G.05` Ports 与转发
- `G.06` Vault、账户分区、会话历史
  - `G.06.01` 跨 Host 搜索、部分结果和重试
- `G.07` 文件夹 Workspaces 与 PR Checks
- `G.08` Plugin Panels、iframe/声明式视图
- `G.09` Standalone/Embedded SidePanel 宿主（目标新增）
  - `G.09.01` 固定目录的 Explorer 独立与嵌入呈现（目标新增）
  - `G.09.02` 选择来源与原编辑器回源（目标新增）
  - `G.09.03` 含 Explorer 的窄窗与列表操作
  - `G.09.04` Explorer 冷恢复、失联与撤回（目标新增）

## H · 文件、编辑器与审阅

- `H.01` 编辑器标题、保存、冲突、外部变化
- `H.02` Markdown 源码、富文档、预览
- `H.03` 专用文件查看器
- `H.04` Diff、合并、多文件、图片
- `H.05` 审阅注释、Git Graph 与检查详情
- `H.06` 文件操作／重命名／外部程序

## I · 内置 Browser 与模拟器

- `I.01` 地址栏、导航、历史和页内查找
- `I.02` 页内容、身份、证书、弹窗和下载
- `I.03` 开发者工具、标注、Agent 浏览
- `I.04` 浏览器扩展、Cookie 与 WebAuthn
  - `I.04.01` 浏览器扩展工具栏与独立弹窗
- `I.05` 远端网页、屏幕流、客体崩溃

## J · 任务及托管审阅

- `J.01` 任务来源、搜索、筛选与列表
- `J.02` GitHub Issues/PR、Project Board 与详情
- `J.03` GitLab Issue/MR 与详情
- `J.04` Linear 项目、视图、Issue、Drawer
  - `J.04.01` Linear 项目表、概览和自定义视图
  - `J.04.02` Linear Issue 抽屉编辑、评论和活动
- `J.05` Jira 项目、快捷筛选、Issue 详情
  - `J.05.01` Jira 列表列、项目筛选和关联工作区
  - `J.05.02` Jira 转换字段、指派与附件
- `J.06` 任务创建和开始工作

## K · ACS 协作消息

- `K.01` 连接入口、空间和联系人选择
- `K.02` 会话历史、读状态、归档与搜索
- `K.03` 发送、附件、草稿、回复
- `K.04` 投递阶段、待确认与查看执行

## L · 自动化、Skills、Artifacts 与扩展

- `L.01` Automations 列表、Host、配置
- `L.02` Automation 执行、日志与删除
- `L.03` Skills 目录、搜索、编辑与分享
- `L.04` Artifacts 列表、预览与打开
- `L.05` 插件管理与目录
- `L.06` 插件授权、Action、Frame 和状态栏

## M · 远程、移动与独立工具窗口

- `M.01` 手机入口、配对、连接与转接
- `M.02` Space、空间管理与迁移
  - `M.02.01` 资源摘要到独立 Space 的结果交接
  - `M.02.02` Space 目录图层级与返回焦点
  - `M.02.03` Space 筛选和清理审阅范围
  - `M.02.04` Space 清理审阅的取消和焦点回接
  - `M.02.05` Space 已确认清理的结果和继续筛选
  - `M.02.06` Space 部分清理与审阅重试
  - `M.02.07` Space 清理失败原因
  - `M.02.08` Space 清理结果与保留分支
  - `M.02.09` 保留分支复核、取消与提交
  - `M.02.10` Space 分支清理部分完成
  - `M.02.11` 复核分支变化和检出占用
  - `M.02.12` 分支拒绝后的保留和重试
  - `M.02.13` 占用分支的工作树路径
  - `M.02.14` 从分支复核打开工作树
  - `M.02.15` 处理占用后继续分支复核
  - `M.02.16` 主工作台显示 Space 返回入口
  - `M.02.17` 回到原 Space 复核的焦点
  - `M.02.18` Space 复核结束和窗口失效
  - `M.02.19` Space 原工作树按钮失效后的焦点
  - `M.02.20` Space 复核的上次检出路径
  - `M.02.21` 工作树移动后的 Git 复核
  - `M.02.22` Space 只读核对当前检出
  - `M.02.23` 检出核对结果与已选分支
  - `M.02.24` 核对后再次占用的提交处理
  - `M.02.25` 配对主机保留分支检出
  - `M.02.26` 配对主机断线恢复与分支重试
  - `M.02.27` WSL 分支路径与重试
  - `M.02.28` 在原配对主机恢复分支核对
  - `M.02.29` 独立 SSH 工作区的主机接入
  - `M.02.30` WSL 停止后从原行启动并核对
  - `M.02.31` 同版本 Porpita 双机配对
  - `M.02.32` 接管既有独立 SSH 项目
  - `M.02.33` SSH 接管后的真实检出与重试
  - `M.02.34` Linux 图形客户端的配对与键盘焦点
  - `M.02.35` Linux 键盘与读屏进入独立 SSH 接管
  - `M.02.36` Linux 读屏下的分支复核、重连与重试
  - `M.02.37` Wayland 原生配对、SSH 与复核键盘路径
  - `M.02.38` Git 成功回执自动播报
  - `M.02.39` GNOME Shell 系统快捷键与客户端焦点交接
  - `M.02.40` GNOME 系统通知中断后的 Git 成功回执
- `M.03` Agent Dashboard、弹出与跳回
- `M.04` 服务器、SSH、WSL、虚拟机
  - `M.04.01` WSL 停止、Windows 盘与迁移提示
  - `M.04.02` 窄窗口内区分同前缀 SSH 主机
  - `M.04.03` SSH 主机键盘选择和读屏名称
  - `M.04.04` SSH 行内连接确认和读屏回执
  - `M.04.05` 配置导入的同前缀 SSH 目标
  - `M.04.06` 720px IPv6 目标辨识与 Orca 播报
  - `M.04.07` 首次 SSH 主机密钥确认
- `M.05` 设备身份、本地运行时和权限
  - `M.05.01` Host/地址选择和自定义地址

## N · Settings 框架

- `N.accounts` AI 提供商账号与配额
- `N.advanced` 高级、网络、镜像与诊断
- `N.agents` Agent 列表、默认启动、Host 能力
- `N.appearance` 外观、主题、字体与窗口
  - `N.appearance.01` 主题、语言、字体、App 图标及缩放
  - `N.appearance.02` 窗口材质、减视觉效果与侧栏
- `N.artifacts` 工件偏好与可见性
- `N.automations` 自动化偏好与入口
- `N.browser` 浏览器、路由、UA、扩展、Browser Use
  - `N.browser.01` 默认主页、搜索、缩放、UA 和站点权限
  - `N.browser.02` 链接路由、Cookie、Profiles、密码和扩展
  - `N.browser.03` Browser Use 能力与配置
- `N.chat` Chat UI 默认值、权限及外观
  - `N.chat.01` Chat 字体、代码、对比与权限组
- `N.computer-use` 计算机使用工具、权限及安装
- `N.dev` 开发工具／诊断
- `N.developer-permissions` 开发者权限与平台检测
- `N.experimental` 实验选项、Dashboard/Pet 等
- `N.floating-workspace` 浮动工作区选项
- `N.general` 通用、窗口/项目、编辑器、CLI、关于
  - `N.general.01` 协作 Core 状态与连接
  - `N.general.02` 准备本机 Agent、导入配置和旧历史
  - `N.general.03` CLI、产品归属与支持
- `N.git` Git、Source Control、AI 提交、API 预算
- `N.input` 输入、编辑与 IME
- `N.integrations` 集成与提供方接入
- `N.linear` Linear 技能设置
- `N.mobile` 移动端设置
- `N.mobile-emulator` 手机模拟器、开启与设备
- `N.notifications` 通知、音效和投递
- `N.orca-account` 产品账户／登录
- `N.orchestration` 原生编排、Crew 和角色配置
- `N.plugins` 插件设置、安装源和权限
- `N.privacy` 隐私、遥测与报告
- `N.quick-commands` 快捷命令列表、排序、作用域
- `N.repo` 动态 Project/Repo 设置与 Host Scope
  - `N.repo.01` 项目身份、Git/任务关联和移除
  - `N.repo.02` 工作树默认、Hook、WSL、符号链接与稀疏配置
  - `N.repo.03` 信任、MCP、格式化和源码 AI
- `N.servers` 远程 Porpita、运行时环境、更新
- `N.session-history` Agent 会话搜索／历史设置
- `N.setup-guide` 设置内入门清单
- `N.share-skills` 分享技能配置
- `N.shortcuts` 快捷键、搜索、冲突、重置
- `N.ssh` SSH Hosts、口令、配置与路径
- `N.stats` 统计和用量
- `N.tasks` 任务来源设置
- `N.terminal` 终端外观、Shell、窗口、会话
  - `N.terminal.01` 终端主题、导入与预览
  - `N.terminal.02` 终端会话容量、管理和结束
- `N.voice` 语音、模型、设备

## O · 覆盖层、通知与安全边界

- `O.01` 全局通知、提醒、提示与静默
  - `O.01.01` 首次使用卡片避让关键操作
  - `O.01.02` GNOME 平铺下的首次使用卡片避让
- `O.02` 平台更新、崩溃、诊断与恢复
  - `O.02.01` Linux 包更新失败与手动安装恢复
- `O.03` 权限、证书、执行与破坏性确认
- `O.04` 可选 Pet、语音及视效
- `O.05` 原生关闭到后台与系统通知
- `O.06` 产品 Profile 切换、导入与恢复
- `O.07` 应用菜单、Help、托盘和支持入口
- `O.local.account-switch` Claude 账号切换与会话树
- `O.local.browser-extension` 浏览器扩展安装确认
- `O.local.browser-webauthn` 浏览器账号认证对话
- `O.local.close` 固定 Tab、运行终端与未保存内容确认
- `O.local.confirm-orca-yaml-hooks` 项目配置与 Hooks 信任
- `O.local.confirm-remove-folder` 移除目录确认
- `O.local.confirm-sleep-twin` 休眠关联工作树确认
- `O.local.contextual-tour` 首用／功能导览浮层
- `O.local.edit-meta` Worktree 元数据表单
- `O.local.forget-ssh-workspace` 忘记 SSH 工作树
- `O.local.link-routing` 链接打开方式确认
- `O.local.macos-update` macOS 更新门槛
- `O.local.trust` Agent 工作区信任
- `O.local.worktree-base` 分支基底回退说明
- `O.local.worktree-visibility` Worktree 可见性
- `O.local.wsl-move` WSL 移动与进度
- `O.modal.add-repo` 添加项目入口
- `O.modal.agent-session-history` Agent 历史选择
- `O.modal.chat-account-usage` 原生 Chat 账号用量
- `O.modal.confirm-add-project-from-folder` 目录升为项目确认
- `O.modal.confirm-non-git-folder` 普通文件夹确认
- `O.modal.crash-report` 崩溃报告
- `O.modal.delete-worktree` 删除工作树确认
- `O.modal.diagram-viewer` 图表查看覆盖层
- `O.modal.feature-tips` 特性提示列表
- `O.modal.feature-wall` 特性墙与演示
- `O.modal.markdown-template-picker` Markdown 模板选择
- `O.modal.new-workspace-composer` 新工作区 Composer 覆盖层
- `O.modal.node-dist-mirror` Node 镜像诊断与选择
- `O.modal.onboarding` 首次设置 Dialog
- `O.modal.preserved-branch-review` 保留分支批量复核
- `O.modal.project-added` 项目接入完成
- `O.modal.quick-open` 文件 Quick Open
- `O.modal.setup-guide` 入门清单弹窗
- `O.modal.ssh-passphrase` SSH 口令队列
- `O.modal.workspace-cleanup` 工作区清理
- `O.modal.worktree-palette` 全局跳转与最近访问
- `O.native.edit-menu` 平台可编辑区域菜单
- `O.native.file-dialog` 平台原生打开、保存、选择目录
- `O.native.recovery` 原生档案错误与写入失败
- `O.overlay.chat-ui-here-corner-card` Chat UI 教育提示
- `O.overlay.codex-shared-settings-notice` Codex 配置提示
- `O.overlay.dictation` 语音输入状态
- `O.overlay.floating-workspace` 浮动工作区 Host
- `O.overlay.native-chat-resume-on-restart` 重开后的原生会话恢复
- `O.overlay.pet` Pet 浮层
- `O.overlay.recent-tab-switcher` 内容 Tab MRU
- `O.overlay.remote-server-update-dialog` 远程服务更新
- `O.overlay.skill-freshness-update-dialog` 技能更新详情
- `O.overlay.star-nag` GitHub 提示卡
- `O.overlay.star-nag-toast` 价值时刻提示
- `O.overlay.status-bar` 状态栏 Host
- `O.overlay.telemetry-first-launch` 遥测首次选择
- `O.overlay.unexpected-signout` 异常退出登录
- `O.overlay.update-card` 更新进度和失败
- `O.overlay.zoom` 窗口缩放反馈

## P · 视觉与基础组件

- `P.01` Button、Button Group、Toggle、Toggle Group
- `P.02` Input、Textarea、Label 与表单
- `P.03` Select、Command、ComboBox 与搜索
- `P.04` Menu 与 Context Menu
- `P.05` Popover、Tooltip 与 HoverCard
- `P.06` Dialog、Sheet、SecuritySurface
- `P.07` Checkbox、Radio、Switch、Slider、Color Picker
- `P.08` Card、Badge、状态指示与进度
- `P.09` Tabs、Disclosure、分隔线
- `P.10` 滚动区、虚拟列表和溢出
- `P.11` Sonner、Toast 层级与临时反馈
- `P.12` 字体、色彩、图标、间距、尺寸、圆角
- `P.13` 可访问性、语言、主题、系统材质

## Q · 动效与时间关系

- `Q.01` 窗口与页面进入/切换
- `Q.02` Sidebar/Dock 的打开、缩放和隐藏
- `Q.03` Tab 激活、移动、溢出和 Pane 拖放
- `Q.04` 弹窗、Sheet、菜单与通知进出
- `Q.05` 虚拟列表、展开与定位反馈
- `Q.06` 流式内容、运行、加载与恢复
- `Q.07` 教育、媒体、提示及特效

## R · 用户路径与连续操作

- `R.01` 首次启动 → 选择工作方式 → 首次会话
- `R.02` 添加项目 → 日常搜索 → 设置 → 原工作点
- `R.03` 找 Session → 打开 → 跨组定位已有（目标新增）
- `R.04` 组合 Session 与 Panel → 分屏 → 调整和恢复（目标新增）
- `R.05` 发起原生工作 → 等待与审批 → 检视 → 继续
- `R.06` 后台运行 → 关闭呈现 → 退出 → 重开
- `R.07` 固定 SidePanel → 换 Session → 移入移出（目标新增）
- `R.08` 文件与任务来源 → 编辑、Diff/Review → 原会话
- `R.09` 任务/协作/自动化 → 结果 → 源工作对象
- `R.10` 扩展发现 → 权限 → 承载 → 撤销
- `R.11` 使用 Browser、远程／配对辅助 → 返回
- `R.12` 部分失败、断线／撤权 → 检查 → 同对象恢复
- `R.13` 输入、主题、语言、窄窗、减少动效 → 重复主路径

## S · 状态与恢复规格

- `S.01` 当前、悬停、按压、选中、键盘焦点
- `S.02` 首次/无项目、无记录、过滤无结果
- `S.03` 首载、延迟、局部刷新与过时数据
- `S.04` 提交中、运行、排队与流式
- `S.05` 待输入、批准、凭据与信任
- `S.06` 不可用、只读、禁用、失权
- `S.07` 失败、未确认、部分完成与安全重试
- `S.08` 断开、重连、恢复与旧状态
- `S.09` 预览、未保存、关闭与终止

## T · 输入和连续交互规格

- `T.01` 点击、双击、中键与选择
- `T.02` 右键、悬停与弹层退回
- `T.03` 拖放、重排、分屏、调整与取消
- `T.04` 焦点、快捷键、键盘导航与 IME
- `T.05` 窗口缩放、折叠、展开与滚动
- `T.06` 切换、历史返回和恢复焦点

