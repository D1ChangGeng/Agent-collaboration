# ACS 授权、到期与机器使用限制清理范围

日期：2026-10-12，Asia/Tokyo。
状态：静态盘点与清理范围已确定，运行实现尚未修改。
源码基线：`e208a44f49927ead846623916ada828277401d00`。

## 1. 本轮范围

按用户确认的业务价值和实际能力，保持项目、协作者、工作、通信、成果、
交接与评审的业务关系，清理默认单安装者路径中的授权层次、人工到期和
Harness 使用限制。Project、Route、WorkItem 是否可以省略及新增寻址方式，
属于另一组业务选择，本轮不借清理授权改变这些关系。

默认连接使用安装者已经确认的身份、机器和环境。角色表示协作职责，
运行时事实表达实际连接和进程状态。用户明确撤销、更换机器或账号需要
重新登录时，按真实原因处理。

以下 34 项以实现中的实际条件为依据。源码存在条件不等于每个部署都
采用同一受限 Profile；私有集成和不同安装版本须在实施时核对实际调用路径。
运行速度和质量改善为预期，尚未执行删除后的性能与产品旅程测量。

## 2. 处理含义

- **清除默认门槛**：默认单安装者协作不再依赖该资格、到期或限制。
- **移至可选策略**：共享部署、特定项目或专用隔离环境按选择启用。
- **合并**：相同事实在一次操作上下文中读取和判断一次。
- **运行维护**：由真实连接和进程生命周期管理，不由调用者续期。
- **保留实际职责**：提交去重、对象定位、具体进程归属和结果关联仍正确执行。

## 3. 授权与使用资格：8 项

| 编号 | 当前条件及实现入口 | 确定处理 | 业务影响 |
|---|---|---|---|
| A01 | 本地 Owner Grant 默认 365 天，操作要求当前未到期；`runtime/domain.py` 的 `bootstrap_local_grant`、`_authorize` | 清除默认安装者内部授权自然到期；持续信任直到明确撤销或变更 | 已配置安装跨长期使用保留；服务入口仍确认连接身份 |
| A02 | Project、Route、成员的派生 Grant 与委托链逐层验证；`runtime/project_service.py`、`runtime/project_routes.py`、`runtime/domain.py` | 逐角色和逐层权限退出默认路径；共享服务移至可选策略 | 组织关系及职责保留，普通协作无需维护独立授权树 |
| A03 | Profile 和多个 permission 控制工具发现及每次项目调用；`runtime/project_service.py` 的 `_discover_tools`、`_authorize` | 默认工具按实际实现和适配能力发现；身份与操作对象统一校验 | 工具不因内部角色权限观测陈旧而消失 |
| A04 | Anchor、Project、Route 对同一权限及委托链重复计算；`runtime/project_service.py`、`runtime/domain.py` | 合并同一操作的共同判断；删除默认授权树后去掉对应查询 | 减少同一请求的查询与锁开销；跨实际执行边界保留状态确认 |
| A05 | Team 强制成员 permissions、Grant、expires_at、budget_ref；`runtime/project_management.py` 的 `TeamMember`、`_configure_team` | 默认 Team 配置聚焦成员、职责与 Harness 选择；额外授权配置移至可选策略 | 创建协作成员更直接；成员与会话身份仍可记录 |
| A06 | Team 的消息数量、待处理数量、预算到期和 activation 限制；`runtime/team_policy.py` | 人工预算和能力限制移至可选策略；原生实际忙碌和队列调度保留 | 已接入能力按请求使用；真实队列承载与重试控制继续工作 |
| A07 | 生产者、观察者、Reviewer 的现役 Grant 与委托链限制历史证据、Review 和接受；`runtime/domain.py`、`runtime/effect_domain.py` | 清除自然到期对历史事实的失效传播；保存形成时身份、候选及结果 | 已完成结果跨会话可继续使用；当前决定与明确撤销事件分别处理 |
| A08 | 源码及成果每次读写叠加 `source.read`、`artifact.read` 等角色授权；`runtime/data_policy.py`、`runtime/project_service.py` | 默认沿用安装者确认的项目与资料入口；细分数据授权移至共享策略 | 保留文件定位、资料边界、秘密排除和成果摘要，减少重复资格校验 |

## 4. 到期与自动失效：11 项

| 编号 | 当前条件及实现入口 | 确定处理 | 业务影响 |
|---|---|---|---|
| T01 | Connection 登记有 expires_at；查询与远程发送按时间过滤；`runtime/receiver_domain.py`、`runtime/project_service.py`、`runtime/remote_endpoint.py` | 清除人工登记到期作为机器使用资格；保留连接配置及真实可达性 | 空闲一段时间后直接重连，不再因历史登记失去机器 |
| T02 | Endpoint 与 delivery_endpoints 分别到期，查询取最早时间；`runtime/receiver_domain.py`、`runtime/project_management.py`、`runtime/delivery.py` | 清除其人工资格寿命；Runtime 按接收程序实际状态准备入口 | 重启后重新建立当前绑定；旧记录不会被直接当作在线进程 |
| T03 | Node binding、Runtime registration 到期依赖 producer/observer Grant；`runtime/enrollment.py`、`runtime/harness_sessions.py` | 机器长期身份与进程实例分开；移除默认登记到期，自动维护实际实例 | 保留 boot、会话和请求关联，取消常规重新证明资格的流程 |
| T04 | ACS Authority transport key 的数据库到期阻断协议；`runtime/receiver_domain.py` | 清除默认内部信任记录自然到期；按明确轮换与撤销更新 | 保留密钥身份和真实连接认证；外部证书有效性按协议自动管理 |
| T05 | MCP 普通命令默认 30 秒 deadline，Domain 时间失败归为授权拒绝；`runtime/project_service.py` 的 `_command`、`runtime/domain.py` | 清除默认短期资格窗口；RPC、数据库等内部超时单独管理 | 耗时处理不会被误报为用户无权操作；请求身份和版本冲突继续校验 |
| T06 | Message 业务寿命由 Grant 链、Team budget 等最早到期裁切；`runtime/project_service.py` 的 `_message_expiry` | 清除授权及人工预算对默认任务寿命的裁切；用户选择的有效期单独表达 | async/sync/wait、执行限制与任务有效期继续分开，长任务可跟踪 |
| T07 | EvidenceBundle 可带 expiry，接受 valid_until 包含多个参与者 Grant 与命令到期；`runtime/domain.py` 的 `_guard`、`_validate_bundle` | 普通持久成果不因自然时间流逝失效；真实时效性业务由项目明确选择 | Review 与候选关系保持；结果完整性和明确失效事件继续可查 |
| T08 | 通知 Session 绑定固定 300 秒，过期后无法获取 wake keys；`runtime/project_continuation.py` | 按实际订阅连接生命周期维护通知；断线依靠持久 Inbox 恢复 | 等待较长工作不会因通知资格超时而静默失去回传 |
| T09 | 原生 readiness 使用固定 2 秒 lease / freshness 窗口；`runtime/native_delivery.py` | 移除固定时间票据作为可执行资格；在实际提交点读取原生状态或使用原生调度 | 保留忙碌处理和选择的投递语义，减少证明过期造成的误拒绝 |
| T10 | Node 的操作 challenge 为短期证明，多层 admission、prepare、dispatch 再绑定期限；`runtime/enrollment.py`、`runtime/receiver.py`、`runtime/sender.py` | 普通执行沿已认证连接提交；独立短期证明移至需要它的协议或策略 | 保留请求 ID、签名或连接身份与单次处理状态；旧请求不会作为新任务再次执行 |
| T11 | Recovery/Incident 的期限、现役绑定及原派发寿命影响响应投影或恢复；`runtime/recovery_service.py`、`runtime/response_collector.py`、`runtime/codex_driver.py`、`runtime/opencode_driver.py` | 结果保存和历史读取与当前调用资格分开；具体业务失效只影响后续决策 | 迟到结果可以保存并解释；归到原 Attempt，不把旧结果覆盖到新工作 |

这里的清理针对 ACS 人工资格到期。Connection Clock、持续时间时钟、
真实网络超时、用户明确的任务期限和外部平台实际凭据有效性分别保留。
选择任务到期也不应删除已经产生的历史结果。

## 5. Harness 与机器使用限制：11 项

| 编号 | 当前条件及实现入口 | 确定处理 | 业务影响 |
|---|---|---|---|
| H01 | Codex 要求 multi_agent 和 multi_agent_v2 为 false；`runtime/codex_driver.py` 的 `_settings`、`spawn` | 清除默认强制关闭；原生能力按安装者设置和实际 API 使用 | Harness 的内部委派可使用；Core 记录它实际能观察的执行范围 |
| H02 | OpenCode 全局与 Agent 配置要求 deny-all，并禁止 task 工具；`runtime/opencode_driver.py` 的 `OpenCodeLaunchProfile.validate`、原生配置检查 | 限制 Profile 留在选用该环境的测试或专用策略；普通执行使用选择的原生权限 | 普通 Harness 工具可用于真实工作，保留原生审批与能力事实 |
| H03 | OpenCode 要求 MCP 和插件为空；`runtime/opencode_driver.py` | 清除普通执行的空配置要求，使用已选择接入环境的配置 | 执行 Agent 能使用其已配置的连接器、工具和插件 |
| H04 | 禁用项目配置并拒绝 .opencode/custom-tool 内容；`runtime/opencode_driver.py` | 清除普通执行中的项目配置禁用要求 | 项目自身的工具与运行设置可以生效 |
| H05 | OpenCode 要求多套独立且 fresh 的 home/data/state/cache/temp roots；`runtime/opencode_driver.py` | 一次性干净环境变为可选执行环境；默认复用选定接入配置 | 已配置工具、模型和认证可持续使用；临时文件与运行实例仍可分开 |
| H06 | Codex 强制 approval_policy=never 与固定 permission profile；`runtime/codex_driver.py` | 普通执行尊重安装者选定原生权限和审批设置，移除固定 Profile 门槛 | 必要原生审批按真实流程处理；ACS 不重新压低所选环境能力 |
| H07 | 配置 digest、固定 Agent/provider/model 与每次实时设置校验成为启动资格；`runtime/codex_driver.py`、`runtime/opencode_driver.py` | 配置用于记录与更新检测；受支持修改按新配置准备下一操作 | 用户正常改模型或工具不会造成整个环境失去资格；操作输入与会话关联仍明确 |
| H08 | 仅接受硬编码的少量 Harness 版本；`runtime/codex_driver.py`、`runtime/opencode_driver.py` | 普通接入采用实际 API 能力与兼容性检测；固定版本用于对应工程验证 | 支持兼容的新版本；真实接口不兼容仍明确报告 |
| H09 | OpenCode 拒绝代理与环境覆盖，Receiver 使用受限运行环境；`runtime/opencode_driver.py`、`runtime_deployment/receiver_codex.py` | 普通执行沿用安装者选定环境；测试环境的特定环境表按环境选择启用 | 正常网络、服务商和工具配置可用；凭据保持受保护加载与输出规则 |
| H10 | attach 只读，所有 mutation 要 exclusive_owned，控制资格要求 ACS 拥有完整启动进程；`runtime/codex_driver.py`、`runtime/opencode_driver.py`、`runtime/native_delivery.py` | 按实际原生 API 区分读、发消息、执行、取消；对每项操作保留具体目标与真实控制权 | 可以扩展已有会话接入；无法控制的操作仍返回实际能力边界 |
| H11 | 专用隔离 Profile、容器只读/无网络设置及强隔离证明限制普通运行路径；`runtime/supervisor.py`、`runtime/systemd_supervisor.py`、`runtime_deployment/receiver_codex.py`、`tools/runtime/gate_runner.py` | 专用隔离环境按选择启用；普通执行保留可用的进程管理，不以取得隔离证据为启动条件 | 普通工作可以使用所选环境；专用隔离仍有独立适用范围与保证 |

H02–H09 确认的是对应公共 Driver / Profile 的条件。不能推断所有本机交互会话、
私有 Overlay 或接入环境都已经受到同一限制。H11 中部分隔离设置属于具体
Supervisor 或工程 Profile，普通接入须与该环境区分。

放开固定 Profile 后，停止已拥有的进程仍需准确定位；接入共享原生 server
时应使用具体会话取消 API，不能为停止一项工作杀掉整个共享 server。

## 6. 关联条件与误判：4 项

| 编号 | 当前条件及实现入口 | 确定处理 | 业务影响 |
|---|---|---|---|
| R01 | Scope 同时用于业务寻址与独立权限资格；`runtime/project_service.py`、`runtime/project_routes.py` | 角色/Scope 权限资格退出默认路径；保留项目、工作及目标关系定位 | 现有业务对象仍明确；跨范围任意寻址作为独立业务扩展评估 |
| R02 | Source 普通接入要求 exact clean baseline，源码控制路径还叠加权限；`runtime/project_source.py`、`runtime/source.py` | 普通读取可准备明确的工作区视图；选用评审快照时保留准确版本 | 正常开发修改可被看见，候选版本与文件内容仍可对应 |
| R03 | Grant、Lease、受保护资源网关被作为整个 Harness 的控制说明；`runtime/lease_authority.py`、`runtime/effects.py`、`runtime/artifacts.py` | 清除超出真实覆盖范围的承诺及普通工作前置；网关能力按实际调用保留 | 保留真实资源并发控制，不声称它限制网关之外的 Shell 和文件写入 |
| R04 | 到期、额度耗尽、身份不匹配等汇入 AuthorizationDenied，陈旧登记汇成 expired；`runtime/domain.py`、`runtime/team_policy.py`、`runtime/project_service.py` | 错误按身份、网络、执行、冲突和明确业务期限分别呈现，并绑定实际恢复动作 | 使用者可以判断具体失败；可恢复运行异常不触发反复授权指导 |

## 7. 必须继续承担的 Core 职责

这些职责接受实现简化，但不能因清理授权而失去：

| 职责 | 直接支撑的业务结果 | 可检查的失败例子 |
|---|---|---|
| 服务入口与目标机器身份确认 | 连接到安装者选择的服务和机器 | 目标服务替换后仍被当作原机器 |
| 项目、任务和会话定位 | 请求与结果属于正确对象 | 相同会话标识在不同环境中被误用 |
| 请求去重与确定性提交记录 | 重连和响应丢失后不重复提交 | 同一请求超时后被重新运行两次 |
| 版本与并发一致性 | 多 Agent 的更新可以协调 | 同时改派任务覆盖了对方决定 |
| 具体进程/会话的控制权与代际 | 停止正确执行，区分新旧实例 | PID 复用或共享 server 上误停止其他任务 |
| 结果与历史归属 | 旧结果可查询且不会覆盖新执行 | 迟到响应被当成新 Attempt 的结果 |
| 原生忙碌处理和选择的投递语义 | 按请求顺序或明确选择送达 | 未选择 steering 却打断了原生当前任务 |
| 实际资源锁与调度承载 | 多次操作使用资源时可以协调 | 两个执行者同时持有同一独占网关资源 |
| 资料定位、秘密保护与内容完整性 | 正确读取项目，保留可靠成果 | 路径变化读错文件或泄露认证材料 |
| Connection Clock、内部超时与可恢复退避 | 分布式时间和暂时故障可处理 | 连接故障无限卡住全部操作 |

上述条件有实际实现依据，涉及 `runtime/auth.py`、`runtime/driver_claim.py`、
`runtime/receiver.py`、`runtime/domain.py`、`runtime/lease_authority.py`、
`runtime/supervisor.py`、`runtime/source.py` 和结果投影实现。

删除它们可能出现业务失败；清理目标是撤去额外资格层，同时保留真实运行
职责。自然到期、人工资格和原生能力限制，与实际去重和进程控制分别处理。

## 8. 对业务模型的影响

| 业务流程 | 清理后保持的能力 | 实际变化 |
|---|---|---|
| 安装、接入机器 | 选择机器、准备环境、验证连接 | 接入关系持续保存，常规使用不再维护人工登记有效期 |
| 项目与 Route 管理 | 身份、资料、工作方向和上下文 | 组织对象不再同时要求一棵默认授权树 |
| Team 与职责 | 成员、职责、组合与工作关联 | 普通成员配置去掉独立 Grant、预算和到期字段 |
| 请求派发 | 明确目标、持久提交、原生执行 | 使用真实状态准备入口，并使用所选 Harness 的实际能力 |
| async/sync/wait | 提交、等待、响应回传 | 调用等待与运行限制独立，任务寿命不受授权树最早到期裁切 |
| Inbox 与恢复 | 跨会话读取、通知和跟踪 | 长等待、重启、自然到期不会让历史结果失去使用资格 |
| 交接 | 上下文、责任转移和确认 | 仍保留实际版本与对象关系，减少现役授权检查的传播 |
| Review 与接受 | Reviewer 选择、候选、意见及用户已选流程 | 保存历史形成事实，解除参与者现役授权与结果内容的耦合 |
| 取消和停止 | 改变工作意图、请求停止具体执行 | 使用当前管理连接处理控制，准确返回实际停止范围 |
| 源码与成果 | 项目资料、修改、版本和成果引用 | 普通读取可反映工作区；需要固定快照的流程仍可选择 |
| Client 观察与配置 | 目录、状态、分析及配置职责 | 展示真实能力与原因，正常配置变更不制造整个环境失效 |

这些变化保持核心业务能力，预期减少配置、查询和误拒绝并放开原生执行能力。
同时，它们取消默认逐角色权限隔离、人工授权有效期和特定受限 Profile 的
保证。这些保证必须在有实际需要的部署中明确选择，而不能继续隐含宣传。

用户已选择的独立评审规则与组织职责保持其业务含义。普通任务是否绕过
Review、是否省略 Route/WorkItem，依业务模型另行决定。

## 9. 技术改动范围

1. **服务身份入口与业务操作上下文**：默认安装者路径使用已确认连接身份，
   与可选细分授权策略分开；保留当前服务、项目和请求的具体定位。
2. **登记与执行准备**：持久机器配置、当前运行实例和操作记录分开；
   查询、派发、Receiver 与恢复服务一起清除人工 expiry 前置。
3. **原生 Driver**：增加普通接入路径，使用所选原生环境；受限参考 Profile
   回到其实际测试或专用环境。原生 API 能力检测负责兼容性与控制范围。
4. **消息与结果**：派发资格、等待时长、运行限制、业务有效期与历史结果读取
   分开；响应丢失只恢复原操作的跟踪，不重复执行。
5. **历史证据与 Review**：记录形成时的身份及对应候选，按当前决定处理接受；
   单独记录明确撤销或真正时效性业务规则。
6. **数据库、MCP schema、配置与 Skills**：默认工具输入不再要求额外授权、
   预算或到期资料；转换现有登记，保留历史引用和原请求 handle。
7. **Client 与文档**：状态和错误对应实际原因，默认产品能力与可选策略分别
   说明；清除重复授权、人工续期和固定受限环境的默认指导。

Grant、deadline 等字段散布在数据库外键、类型、签名和请求 hash 中；
直接删字段或让 `_authorize` 总是成功不能完成迁移。迁移须保持原请求
身份和历史查询；已有共享部署保留现有访问边界直到其策略映射明确。

同步修改入口包括 `runtime/*.py`、相关 schema 与升级代码、
`runtime_deployment/receiver_codex.py`、安装/启动/升级脚本、MCP 工具合同、
`docs/runtime/skills/`、`SKILL.md` 和相关 Client 设计说明。
工程 Gate 的历史记录继续绑定原版本，不修改为新路径的通过证据。

## 10. 实施顺序与验收

### 顺序

1. 先完成“已保存机器配置 → 实际连接 → 准备入口 → 真正执行 → 结果回传”。
2. 同时迁移 Connection、Node、Runtime、Endpoint 的人工 expiry 与默认授权路径，
   覆盖查询、发送、Receiver、Driver 和恢复，而非只改列表显示。
3. 放开普通 Harness 配置与原生工具，测量完整可执行工作。
4. 分离消息寿命、控制请求、通知连接与历史结果。
5. 解除 Review/证据对现役 Grant 的耦合，同步存储、接口和 Skills。
6. 在兼容路径迁移完成后清除对应默认代码，检查残留门槛和说明。

### 验收场景

- 机器配置一次后，模拟旧登记到期，仍能自动准备执行入口并完成真实任务。
- 空闲、网络中断、机器重启和管理会话替换后，原项目与结果继续可用。
- 长任务跨越原 30 秒命令窗口、2 秒 readiness 和 300 秒通知窗口后，仍能收到结果。
- 改变模型配置或安装兼容版本后，按真实能力继续接入。
- 执行 Agent 可以使用已选择环境的 Shell、编辑、任务工具、MCP 与插件。
- 已存在会话按实际 API 获得声明的观察、发送、执行或取消能力。
- 原参与者会话结束或内部旧 Grant 到期，历史结果、Review 和后续决定仍可查询。
- 同一请求重试不会重复运行；旧结果不会覆盖新 Attempt；停止不会影响其他任务。
- 用户已选择的独立 Review 与固定候选核对继续按业务要求工作。
- 真实离线、账号需登录、接口不兼容等故障返回准确原因和恢复状态。
- 从同一仓库链接由本机与网页入口完成协作旅程，比较必要用户步骤、
  工具往返、完成时间与任务结果；这些指标才是效率和质量改善的证据。

## 11. 结论

本轮 34 项清理对象覆盖默认授权资格、人工登记到期、原生环境限制以及
由它们传播到历史结果、通知和产品状态的关联条件。清理保持现有业务关系，
释放已接入 Harness 的实际能力，恢复责任由 Runtime 承担。

范围确定与实现完成分别记录。当前文档完成静态盘点和影响分析，
未声称已经移除运行中的检查或通过清理后的产品旅程。
