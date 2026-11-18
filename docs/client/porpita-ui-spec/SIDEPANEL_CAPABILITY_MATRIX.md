# SidePanel · Scope、宿主与迁移顺序

当前 RightSidebar 是 App Shell Dock。`right-sidebar-panel-content.tsx` 按 `effectiveTab` 分派，`use-right-sidebar-activity-items.ts` 对 folder、Git、SSH、插件条件筛选，旧 `search` 路由折回 Explorer 的内容视图。开发预览把第十一轮的本机实例扩展为可选本机、配对 Runtime 来源的固定 Explorer。其它工具继续按各自的源和目标条件判断。 [第 11 轮](ITERATION_11.md) · [第 24 轮](ITERATION_24.md)

| ID / Definition | 当前依赖与内部状态 | 初代呈现与复用 | 移动前须验证 |
| --- | --- | --- | --- |
| G.02 Explorer | worktree/folder root、Host；名称/内容、展开节点、选择、查询、滚动和搜索结果；文件打开另走编辑器 | Dock 按工作树、owner 和显示根恢复文件名筛选。Standalone/Embedded 预览沿用 Orca 单目录文件列表、名称筛选、归属检查和编辑器。 [第 8 轮](ITERATION_08.md) · [第 24 轮](ITERATION_24.md) | 完整多级树、Contents、修改前后刷新与写操作 |
| G.03 Source Control | worktree 或 folder 分支；Changes/History/Branches、选择、提交草稿、stage 与远端请求 | 保留 Dock；第二个独立/嵌入候选；复用现有 Git 内容 | Git owner 严格绑定，切换/移动保留草稿与内部 Tab，任何写操作都不能落到活动的另一个仓库 |
| G.04 Checks | Git workspace、provider/review 映射、状态列表与详情 Tab | 先 Dock；待固定 Repo/PR scope 后评估独立只读 | 预览、关联 commit 和深链接均用原 owner；断线与无权限分开 |
| G.05 Ports | Active owner 解析为 SSH Host 能力；发现、转发及转发状态 | 先 Dock；候选 Host-fixed 只读，转发写动作保留原所有者 | 两主机同端口、断线、复连、关闭呈现不停止既有转发 |
| G.06 Vault（Agents） | Provider、账号、Host、历史列表、详情、查询及当前可用的原位定位或恢复 | Dock 支持从工作台跳转面板接收查询。独立呈现沿同一账号和读权限边界。 [第六轮](ITERATION_06.md) | 已回放本地历史、同机配对与重试，以及搜索交接。继续验证真实跨机、账号权限变化和独立呈现。 [第四轮](ITERATION_04.md) · [第五轮](ITERATION_05.md) |
| G.07 Attached worktrees | 仅 folder scope；关联 worktree 及选择 | Dock only，保留 folder 上下文 | 从普通 Git 切 folder 和回退，关系保持 |
| G.07 PR Checks | folder 父级/关联 Repo review、可见状态；服务加载 | Dock only，保持父 folder 的来源 | 换 Host、刷新、检查详情与 PR 链接归属 |
| G.08 Plugin Panels | 配置开关、动态贡献和 tabKey；guest/iframe 或声明式内容，frame key 含 revision；bridge 由 session token 绑定 | Dock only；保留当前生命周期和安全配置，禁用后卸载 | 只在证实旧 frame/bridge 撤销、版本/状态恢复及多实例隔离后允许迁移；需合成插件验证 |
| G.09 通用 Host | Dock width/tab 是壳层偏好。预览独立记录 Explorer 实例 | Tab 与嵌入 Workspace 共用同一固定范围。v3 档案保存 Host、路径、呈现、目录、筛选与选中项，列表重新读取原文件范围。 [第 25 轮](ITERATION_25.md) · [第 26 轮](ITERATION_26.md) | 多级树的展开与滚动、同窗多个嵌入工具、远程物理设备和原生读屏 |

**Scope**：Global、Project、Workspace、Host、Session 是可绑定范围；文件、Git 等还有独立的 worktree/repo/root locator。每种 Definition 声明支持的范围和前提，不能统一塞一个隐式 `activeWorktree`。默认固定；可选 Follow Focus 必须由用户主动开启、显示当前绑定，并在转入不同目标前检查草稿或未完成写操作。缺 scope 显示“选择工作目录/主机”等动作，找不到对象显示原位置和恢复路线，已失权时隐藏无权数据。

**Host 操作**：打开按 Definition+Scope 复用最近相同实例，明确「新建实例」时才新增。移入 Workspace 或从 Pane 移出到顶层：检查目标可挂载 → 保存视图状态和 pending 引用 → 切换所有权与焦点 → 更新源入口；渲染不就绪时保留源可恢复，防双挂载双操作。关闭只关呈现，移除解除布局引用，销毁实例必须显式且列出会丢失的本地状态。内部 Tab 只作用于实例，不创建顶层标签。单击导航、右键菜单、键盘及可拖动目标有等价结果。窄宽度让工具栏收拢、路径可访问，文件树和内容保持独立滚动。

源锚点和相关共享组件见 G、G.01–09 和 H。运行验收见 J04/J07/J08/J10/J12。跨 Host 的工作空间允许一个嵌入 Explorer，同时保留另一个来源的独立实例。两者各持原目录和筛选。

第二轮 Windows 已确认右 Dock 在最小窗临时隐藏后保留 Explorer 名称筛选，放宽和切换工具栏位置仍可使用；也从另一个本地 Git 项目查看实际 Changes。Explorer 目前按 worktree 或 folder owner 重新挂载。第一批独立宿主应把 `owner`、查询、展开和选择提升到同一 Instance，嵌入后仍读取原 scope，并验证从另一个活跃 Session 打开同名路径时的来源。 [实际回放](evidence/iteration-02-windows/run.json)。
