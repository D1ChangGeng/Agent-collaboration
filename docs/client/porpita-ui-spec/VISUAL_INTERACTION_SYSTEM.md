# 共享视觉、组件、状态与动效

状态：基于当前 Orca 实现的继承规范和 Porpita 目标补充。组件定义只在此维护；使用映射见 Coverage Matrix 的 P/Q 条目和[组件调用位置](source-index/primitive-usage.csv)，状态、输入见 S/T。目标布局、动效适配在实现后按 J13 复验。

## 视觉与尺寸

| 职责 | 继承规则与来源 | 在产品中的应用 |
| --- | --- | --- |
| 背景/层级 | `assets/main.css` 的 background/foreground、card、popover、editor-surface、sidebar；subtle hairline、内嵌 shadow-xs、浮层 shadow-floating；`--radius: .625rem` 派生组件圆角 | Shell、Panels、编辑器、确认层按实际边界配色；插件主题只走允许 tokens；安全面保持独立 |
| 状态 | primary 单一确认；accent 轻量选中/悬停，ring 表示可见焦点；destructive 仅结果错误与破坏操作；Git decoration 仅 Git | 会话运行/通信/Host 有文字及形状；未读、选中、可键盘操作不能互相替代 |
| 字体 | Geist 为界面正文；等宽用于命令、路径、代码；正文/普通控件 14、密集行 13、次级 12、元信息 11/10 px；按 style guide 的 Tailwind 角色 | Chat 使用 text-sm/xs/2xs/3xs、chat-code，跟随 Chat 可调文字；Monaco/xterm 有独立字体和光标。CJK fallback 必须看实际渲染，保留原文与代码 |
| 间距/尺寸 | 既有 4px 级 Tailwind spacing；默认侧栏 280px；Settings 左栏 280px；右 Dock 最小 220px、侧 Activity Bar 40px、非 Dock 区算法保留 320px；主窗口最低 600×400 | 窄窗优先收拢次级元信息、保持焦点对象/窗口控件；任务/侧栏各自滚动；内容最小宽高根据工具可用性验证，不用缩字号掩盖裁切 |
| 图标/素材 | Lucide 默认 16px，密集 12/14px；保留文件类型、提供方与 Porpita 现有品牌资源；`ShortcutKeyCombo` 负责快捷键外观 | 仅图标按钮独立命名，显示与实际绑定一致；窗口系统控件、品牌标识和工具图标在浅深/高对比下检查 |

视觉判断来自真实安装版：首屏用亮暗两张等宽卡片比较呈现方式，选择环区分当前项；工作台的浅色背景、两侧低对比区、细分界把注意力留给中部工具内容；设置的左侧 280px 导航和纵向表单适合保留。英文标题混在中文操作说明中，会增加导航的阅读成本；Mobile、入门和自动化模板各自采用现有系统翻译机制。规范不改变 Porpita 品牌/工具主体绘制。

## 组件、状态与焦点

| 选择 | 可复用组件与契约 | 典型使用 |
| --- | --- | --- |
| 主/次动作与字段 | Button CVA、Input、Textarea、Label、SettingsFormControls；焦点/禁用/按下/无效独立，aria-invalid+关联说明；切换焦点保留草稿 | 首用、设置、Native Chat/ACS、Git 提交 |
| 单选与搜索 | Select（已知单选）、Command+Popover（搜索）、repo-multi-combobox（多选） | Session 筛选、项目、模型、设置搜索、跳转 |
| 右键/点击/悬停 | ContextMenu / DropdownMenu / Tooltip / HoverCard / Popover 各有独立语义；Tooltip 默认 400ms，top+4px；关键内容有常驻表达 | Sidebar 行、Tab、文件、Diff、状态栏 |
| Overlay | Dialog 阻塞决策；Sheet 边缘工具；SecuritySurface 隔离权限外观；进入有明确初始焦点，Escape 按层关闭，dismiss 归还原操作或替代焦点 | 确认关闭、首次授权、插件安装、文件/任务详情 |
| 列表与选择 | Tab、Badge、虚拟列表、滚动区域、Accordion、Separator；aria-current/selected 和 focus-visible 分离 | Worktree、Session、面板内 Tab、日志与历史 |
| 反馈 | Sonner、NotificationCardStack、Progress、LoadingSpinner；短暂结果 toast，持续失败和未知在原区；遮罩下旧 toast 不抢焦点 | 工作区创建、附件、Git、更新、重连 |
| 键盘和输入 | 应用→活动的 overlay→实际有焦点工具，各自保留 Ctrl/Cmd 语义；IME 组合时不执行发送、关闭或列表选择 | Chat、xterm、Monaco、Browser guest、侧栏；Shift+F10/Menu 和菜单提供右键替代路径 |

状态的排版保留稳定工具区，局部替换内容。默认/选中/悬停/键盘焦点可并存；空数据、无搜索结果、权限不足各有不同说明和动作；加载不清空旧结果，过时结果标时间和范围；运行可停、排队可取消、等待审批跳到真实对象；超时说明结果未确认，先查结果再重试；断线保留合法只读内容和草稿，恢复校验身份和代次；无权内容不可从缓存显示。长文、缩放、部分加载/失败与服务边界的验收按对应 J 流程。

Vault 行复用 `Button ghost/icon-xs` 与既有焦点环。定位和恢复使用同一行尾位置，随真实目的地变化。行标题可以截断，详情保有可读内容。图标控制继承本地化可访问名称及 Tooltip，扩展动作使用原菜单。次要动作的悬停宽度和透明度过渡沿用原样式，减少动态时即时变化。 [第四轮](ITERATION_04.md)

跨 Host 搜索的来源采用原工作树 Host 徽章。Dock 可用宽度低于 300 CSS px 时，先保留 Harness 与 Host，消息数和时间随详情展开。漏搜提示复用搜索状态区，控件与播报文字保持独立，长来源清单沿用有界滚动；重试回到查询字段。 [第五轮](ITERATION_05.md)

混合 Workspace 沿用同一 Host 徽章，在「选择会话」、Pane 标题和短窗切换菜单显示来源。保留原分屏比例、边界和缩窄后只显示当前 Pane 的规则。重连用 Native Chat 的提示和动作，来源撤回后用有明确移除动作的不可用占位。 [第 21 轮](ITERATION_21.md) · [第 23 轮](ITERATION_23.md)

固定 Explorer 用相同的 Host 徽章和已有文件图标。在独立 Tab 前缀显示远端 Host，嵌入时同一面板标题保留 Host、目录与位置菜单。过滤输入使用方向键选择、Enter 打开与可访问的结果关联。移动面板时直接交接焦点，列表在可用的高度内独立滚动。在减少动态的设置下，等待目录结果时保留静止指示。 [第 24 轮](ITERATION_24.md) · [第 25 轮](ITERATION_25.md)

组合式 Workspace 的用量仍在原 24px 状态栏。指标入口旁的 Host 徽章与会话列表采用同一组件，菜单标题带同一来源。在可确认 Host 但暂时无可见读数时保留用量入口，离线与不可用使用同一行的状态文字。刷新提示服从减少动态，状态变化不改变输入焦点。 [第 27 轮](ITERATION_27.md) · [第 29 轮](ITERATION_29.md)

端口弹层采用已存在的状态栏弹层、Host 徽章和端口行。已确认的计数使用原等宽数字，等待或不可用时留出原图标。嵌入或独立工具的范围保持可辨。资源浮层沿用原标签和指标区域，在本机数据前标明范围。 [第 30 轮](ITERATION_30.md) · [第 32 轮](ITERATION_32.md)

跳转面板底部的历史交接使用 ghost/xs Button 和文字标签。底部动作和键位说明允许在窄窗换行。交接动作跳过面板退场，Vault 输入取得焦点。Explorer 返回后沿用原输入、加载和无匹配样式，在同一工作树范围重新读目录。 [第六轮](ITERATION_06.md) · [第八轮](ITERATION_08.md)

侧栏目录使用内联 Command，标题沿用现有搜索行 14px 主线，来源与目的地用 12px 次级文字。区分可连续访问的列表与拥有焦点的菜单，筛选菜单关闭时焦点回按钮。短窗为目录预留结果空间，全局导航与目录结果各自能滚动。查询、范围与分组更改即时更新结果，历史入口与范围按钮并排。菜单采用原 150ms 入场与减少动态变体。 [第十五轮](ITERATION_15.md) · [第十六轮](ITERATION_16.md) · [第十七轮](ITERATION_17.md)

未打开历史复用 Vault 的紧凑栏、虚拟行与原菜单，完成扫描后让出结果高度，必要错误仍在原处。已开目录的运行标识沿用 `AgentStateDot` 的帮助与减少动态，Host 归属采用原工作树 Host 标签。连接未确认的行仍可辨认来源，行内说明与禁用动作同步。协作连接标签在原 Dialog 中单独显示。 [第十八轮](ITERATION_18.md) · [第十九轮](ITERATION_19.md) · [第二十轮](ITERATION_20.md)

独立布局预览临时限制分隔线可用范围。每个 Chat Pane 预留 320 CSS px，额外 6px 分隔交互区。宽度低于 646px 时切到单 Pane，切回双 Pane 读取已保存比例。切换直接更新几何，减少动态下保持相同内容与焦点规则。顶层选择器采用已验证单行密度；固定 Explorer 的面板标题携带项目与当前目录。 [第九轮](ITERATION_09.md) · [第十轮](ITERATION_10.md) · [第十一轮](ITERATION_11.md)

普通 Dialog 与 Sheet 使用现有 Sonner 提升机制。工作区信任使用显式避让，遮罩在场时隐藏全局 toast 和卡片栈，Escape 留在决策面。安全样式同时用于其他 Dialog；将某个 Dialog 加入避让前，将其错误、结果和重试放入对话框自身。Native Chat 审批使用所属 Session 的消息和输入位置。全局通知不自动改变焦点；持久状态留在所属工具，有限提示在现有机制下可以过期。呈现优先级、验证范围与持续队列要求见 [本轮浮层规范](ITERATION_02.md#浮层与关键操作)。

Space 保留分支复核采用安全 Dialog、原有复选框和通知避让。当前批次的删除结果及可继续复核的分支各自更新。结果栏直接呈现真实回执，复核的入场沿用 Q.04，关闭时由当前入口或筛选接回焦点。Space 文档语言跟随生效的界面语言。 [清理结果](ITERATION_49.md) · [复核与焦点](ITERATION_50.md)

分支批次结果在 Space 的原状态区域更新，禁用复核入口表达提交中的状态。拒绝原因采用原列表行的次级说明。选择和焦点都按行的实际可用性更新，结果与原因使用静态文字。 [批次结果](ITERATION_51.md) · [拒绝状态](ITERATION_52.md) · [恢复动作](ITERATION_53.md)

检出路径采用原复核的等宽文字及列表滚动。打开工作树沿用原 Button 和工作台激活，答复留在对应行。跨窗接续维持原复核控件与选择。 [检出路径](ITERATION_54.md) · [工作台交接](ITERATION_55.md) · [继续复核](ITERATION_56.md)

主工作台的 Space 返回动作采用状态栏现有密度、标准 Button 和磁盘图标。返回时延续原复核焦点环，入口随复核失效直接撤下。 [主窗入口](ITERATION_57.md) · [返回焦点](ITERATION_58.md) · [入口回收](ITERATION_59.md)

工作树实例失效时，原复核行沿用现有的次级状态和等宽路径，使用「上次检出路径」说明记录的时点。「取消」保留标准焦点环。重新提交后的当前路径继续用原列表布局呈现。 [回焦](ITERATION_60.md) · [旧路径](ITERATION_61.md) · [当前检出](ITERATION_62.md)

检出拒绝行的「核对检出」沿用小尺寸 Outline Button。Git 路径继续使用等宽可选取文字，结果以行内状态呈现，焦点留在核对按钮。清理回执继续由提交时的 Git 结果驱动。 [核对动作](ITERATION_63.md) · [结果状态](ITERATION_64.md) · [提交回执](ITERATION_65.md)

配对主机在仓库与提交摘要之间标明来源。本机 WSL 目录在同一行补发行版。暂不可用、配对变化和检出结果沿用分支状态及原按钮位置。恢复后刷新该行，按需滚动以露出仍有焦点的按钮。 [配对条件](ITERATION_67.md) · [WSL 路径](ITERATION_68.md)

主机停止或断线时，沿用原行按钮位置提供恢复。等待文案由实际动作决定，焦点随同一控件保留。独立 SSH 使用原确认对话框和设置页，接入按钮与移除操作各自可见。 [恢复状态](ITERATION_69.md) · [SSH 对话框](ITERATION_70.md) · [WSL 状态](ITERATION_71.md)

服务器卡片沿用连接与版本说明。SSH 接管与重试留在同一行，进度和错误保持可读，列表位置按稳定目标 ID 保持。接管后的分支行复用现有核对、禁用及焦点反馈。用户显式重试时，清理通知用当次结果更新说明、操作和显示时长。 [实机卡片](ITERATION_72.md) · [接管反馈](ITERATION_73.md) · [分支恢复](ITERATION_74.md)

配对对话框使用原 Dialog 的焦点管理，关闭后回到设置页的添加按钮。SSH 主按钮在连接中保留同一焦点节点，状态文本通过原行的礼貌播报更新。分支复核维持原行焦点并播报影响提交的结果。Ubuntu 实机用 GNOME Orca 查验播报，同时保存 X11 焦点和截图。 [配对焦点](ITERATION_75.md) · [SSH 焦点](ITERATION_76.md) · [读屏复核](ITERATION_77.md)

界面内术语：会话 / Session、工作空间 / Workspace、工作树 / Worktree、协作对话 / Collaboration conversation、侧面板 / SidePanel、标签组 / Tab Group。用「关闭工作空间」「移出 Pane」「结束会话」描述各自后果。Host 不可用示例：「无法连接到 构建机。上次读取于 14:20。重新连接」。协作未知示例：「尚未确认投递。查看状态」；收件箱存入、原生接纳和已收到回复不共用“已完成”。设置说明不保证下一步能成功。

## 动效与时间

以下数值如标为「源码」是样式声明，不是实测帧延迟；「目标」为有待验收的行为。现有 easing 未显式声明的使用原 Tailwind/动画样式，记录 computed 值后才能声称其实际参数。

| ID / 触发 | 原生来源 / 时间 | Porpita 目标、停止和反向 | 减少动效与验证 |
| --- | --- | --- | --- |
| Q.01 打开设置 / 切页 | main.css Settings 入场 180ms ease-out | 现有设置保持；频繁 Tab/Panes 激活目标 0ms 选中变化，加载按对象；保留稳定壳 | 移除非必要进入位移；回放打开、返回、双击，记录焦点与内容就绪 |
| Q.02 左栏/Dock 显隐 / 拖宽 | 布局切换、fit；handle transition-colors | 目标：直接响应，无位置插值；拖动 rAF 内写局部尺寸，结束只提交一次；连按以最新意图为准 | 最终几何相同；验收 toggle→open→reverse；窄窗、滚动、xterm fit 单独检查 |
| Q.03 Tab 或 Pane 重排 / 拆分 | TabGroupPanel 操作透明度 150ms；分隔线颜色 100ms ease；几何随拖动直接更新。焦点采用现有 ring | Worktree 拖动释放或失捕保存比例，Escape 与 pointercancel 恢复起始边界。顶层组选择器用次级 Button 状态指出可投放，菜单确认再更新所属组 | 分隔线颜色即时切换；菜单采用原浮层动效。左右分屏和顶层拖放取消分别回放。 [第七轮](ITERATION_07.md) · [第十四轮](ITERATION_14.md) |
| Q.04 Dialog、Sheet、菜单、提示 | Dialog 200ms fade/zoom；Sheet enter 300 / exit 200ms，ease-in-out 样式；update card 200 ease-out / 150 ease-in | 沿用已使用变体，遮罩与命中状态成对，退出后不能有残留遮罩；菜单尽量靠现有 primitive | 降低/取消位移和缩放，保留开关和焦点归还；测短窗、快速反转、焦点恢复 |
| Q.05 逐项列表、折叠/定位 | CSS collapsible down 200/up 180ms ease-out；定位 1.5s、编辑 reveal 1.2s ease-out | 避免全列表闪动；稳定 ID、保持读点；定位仅局部且可中断，新结果不冲走筛选和选中 | 直接定位，使用静态可见标记；回放打开、折叠、虚拟滚动与键盘 reveal |
| Q.06 等待与流式 | 工程 Style Guide：<100ms 不提示；100ms–1s 可禁用；1–3s spinner/标签；>3s 多阶段进度；约 200ms 延迟显示以免闪 | 提交即时确认意图，结束依据真实结果；流式保持阅读锚点；返回仍看到同一内容，停止或失效不用动画伪装成功 | Spinner/shine 用静态状态词；短/长等待、流中断、减少动态偏好与读历史并行检查 |
| Q.07 入门/教学/媒体 | Onboarding 布局过渡 760ms cubic-bezier(0.22,1,0.36,1)；步骤条 300ms；各域 CSS keyframes 见索引 | 保留教学演示和普通工作区别；用户切步骤/关闭后停止；媒体按用户播放选择、定向焦点，后台不播非必要特效 | 可读静态等价；跳过、返回、关窗、字体到达、短高度都回放 |

性能目标（实现后量测）：本地常见动作到第一可见反馈 P95 ≤100ms；服务完成时间独立报告；拖放/调宽在参考机器 60Hz 视口下避免主线程长任务，以 frame trace 检查 P95 更新节奏、掉帧、对象归属和输入回显。Windows 后台 CDP 证据用于状态和画面，帧泵和截图开销不作为自然速度。支持 OS 减少动效与可读的静态状态，避免全局零时长导致业务事件或焦点时序变化。验收先测默认，再按 J13 的平台、主题、语言和尺寸矩阵补齐。

终端默认界面的 Chat UI 首次使用卡片在设置或模态期间即时隐去，工作台可恢复当前提示。Git 批量结果在复核遮罩退出后进入既有通知状态区域。仍在运行时才发布进度，完成后用同一通知呈现结果。实测检查主要按钮的中心命中、键盘焦点和 Orca 的最终语句。 [回执规范](ITERATION_79.md) · [卡片规范](ITERATION_80.md)

GNOME Shell 通过 Super+V 打开系统通知。返回 Porpita 后，应用的 Alt+T 继续进入应用内通知。Escape 作用于当前接收输入的界面，系统通知退出后，客户端可以继续原复核。平铺重排保持 SSH「连接」按钮焦点及命中。 [键盘规范](ITERATION_81.md) · [中断后的回执](ITERATION_82.md) · [平铺](ITERATION_83.md)

SSH 主机条目的别名和连接地址是执行动作前必读的身份。窄窗允许它们自然换行，现有按钮和状态随同一条目重新排布。连接按钮的读屏名称按动作、别名、地址排序，成功状态用一条完整语句播报所连接的目标。 [窄窗辨识](ITERATION_84.md) · [读屏名称](ITERATION_85.md) · [连接确认](ITERATION_86.md)

从 SSH 配置导入的目标保留原别名，地址呈现解析出的用户名、主机和端口。IPv6 字面量用方括号界定。首次密钥确认使用安全弹层，先呈现身份和指纹，默认聚焦取消。信任按钮的读屏名称包含本次握手的完整目标。 [IPv6 表示](ITERATION_88.md) · [安全弹层](ITERATION_89.md)
