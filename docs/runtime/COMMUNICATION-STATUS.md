# ACS 通信核心：实现与支持记录

本记录核对开发包 v2.33 的 R01–R34 与当前源码，接续
`f6195bf25d7b6a6fb1c2df3c211028787b2eb29f`，并更新至 v2.3.0 的资格范围。
源码、软件发行版和生产服务是不同状态；旧 Release/Gate 的结论保留原版本范围。

v2.3.0 身份与 Root 管理修复将目录更新为 12：首次 `read_profile` 明确区分
Client 与绑定角色，Root 统一配置入口复用现有登记/团队机制，上下文动作、
工具发现和实际调用共同校验授权。Project 保留通信隔离标识，不增加独立管理
生命周期。设计与兼容说明见 [Root 管理](ROOT-MANAGEMENT.md)。实际生产版本
和切换结果以安装读回及生产验收为准。
[身份与 Root 验收](../../integration_evidence/acs-identity-root-20261102/REPORT.md)
记录四个独立模型、三次原 Session 续接、真实 stdio/HTTP 与受限权限正反例。
[v2.3.0 生产切换](../../integration_evidence/acs-identity-root-production-20261102/REPORT.md)
记录两端安装、Windows/WSL 新连接、真实 Native 关联回复、代次 8 与原有数据保留。
升级前的旧 MCP 通道已回收，现有聊天需要重连以取得新版工具目录。

## 实际可用的主链

普通 A 从通讯录取得 B，发送自然消息；ACS 持久提交并按激活选择通过真实
接收端发起 Native。独立 B 用自己身份的普通 `send_message` 向 A 主动关联
回信；A 从等待结果、Inbox 或历史取得同一回复。原生完成输出不参与匹配。

已实际运行 Windows Codex A → 1302-1 Owner OpenCode B：默认 stdio 入口维护
投递、TLS 指纹与签名接收、一次 Native prompt、两个独立模型、两条消息、
一条明确回复，评测器派发次数为零。配置阶段返回实际读回的同一 Session。
该实验使用隔离 Authority、私有配置及已授权 Provider，不切换正式服务。

已安装 console entry 也完成了独立模型主链：WSL 内 Codex 0.146.0 A 与
OpenCode 1.18.34 B，通过真实 `acs-receiver --config`、默认 stdio 维护器和
双方普通 MCP 收发。一次 Native 发起、两条消息、一条主动回复，ACK 确认送达。
退出后 Native 自有进程组为空，整个安装清单仍一致且没有额外字节码。
这是同一 Linux 主机的实际安装验证。后续 v2.1.0 增加反向物理 Native、
OpenCode Shared/Systemd、Linux 持续负载及两端生产升级；v2.2.0 增加
Codex Shared 真实双模型和 OS 边界验证。Windows 直连 WSL 测试库的历史
两次超时及后续完整负载复测分开保留，详见下方证据。

用法及采用命令见 [COMMUNICATION.md](COMMUNICATION.md)，机器可读接口见
[工具目录](p2-mcp-tool-contract.json)。目录版本为 12（v2.2.0 发行目录为 11），Message 为
`acs-message/1`，Core/Project Schema 为 2。现有旧库需要显式采用；正常启动
只读校验，不执行迁移。软件包版本为 2.3.0；开发包 v2.33 是文档版本。

## 支持声明和验证层次

| 范围 | 已取得的证据 | 限制 |
|---|---|---|
| 普通 Slot/Client 的自然收发、权限和回复等待 | 真实 PG、独立 stdio/HTTP 入口、配对反例；独立模型主链 | 同一 Owner 的普通 Profile 不等于 Shared 受限 Harness 已资格化 |
| Windows Codex Native 接收器 | 正式 Factory、真实 Node/Runtime、Session 准备、自主 MCP 回复、ACK 未知防重 | 精确二进制版本和源清单见对应报告，不推广到任意 Codex 版本 |
| Windows Codex → 1302-1 OpenCode Native | OpenCode 1.18.34 Owner、正式 Factory/签名协议、默认入口自动投递及自主回信；v2.1.0 另有反向物理方向 | 精确主机、Harness 与访问模式见各次源清单，不外推全部组合 |
| 重连和进程中断 | 四个实际 MCP 进程、强制结束等待者、PG 原消息/回复、显式请求键重试 | Agent 由脚本驱动，不计双模型故障恢复验收 |
| 忙时、异常、防重、上行通知和配置竞态 | 真实 PG/SQLite/HTTP，加明确标记的受控 Adapter 与并发时机 | 不据此宣称所有真实 Harness 故障窗口和模型消费均已验证 |
| Shared 身份与签名接收授权 | 真实 PG 权限、Node 身份、发件人重验、撤销反例；OpenCode 1.18.34 和 Codex 0.163.0 的 Linux Shared/Systemd 独立模型闭环 | 仅所列精确受限配置；Codex 含真实 OS 读写、范围外读取与网络正反例；Windows Shared 需另行资格化 |
| 安装与生产 | wheel 安装完整性、provisioner、console；v2.1.0 WSL 服务和物理接收节点切换、服务读回、数据保留及公开发行 | 各版本升级状态以对应恢复验收材料为准，不由隔离模型实验代替 |
| 长正文和资源 | UTF-8 续读、独立回复字节预算、实际单模型续读、四个并发投递上限 | 未建立 p95、吞吐 SLA、大规模持续负载或模型成功率结论 |

## R01–R34 逐项源码核对

下表的“核验”指所列机制和具体样本。真实模型、实际协议及受控故障的证据
分别标示，不能把表格条目或组件绿色等同于全平台验收。路径均相对仓库根目录。

| R | 当前机制与源码 | 已有核验与边界 |
|---|---|---|
| R01 Bridge 边界 | `communication.py`、`native_delivery.py`；自主消息与最小 Native 发起 | 真实双模型回信，Collector/SSE 关闭；工作计划和判断由 Agent 承担 |
| R02 任务域退出 | `domain.py`、`project_service.py`、`communication_core_schema.sql` | 46 表新装没有旧 Work/Review 等 36 表；技术入口拒绝旧任务命令，历史库只读 |
| R03 稳定身份 | `communication.py`、`communication_management.py` | 同 Principal 不同可信 Slot、显示名更新、原作者与旧回复关系不变；实际 Native Session 读回 |
| R04 可信作者 | `auth.py`、`project_service.py`、`runtime_deployment/receiver_authority.py` | Slot 冒用、第三方读取、撤销、重绑旧凭据及封存包作者反例 |
| R05 三级管理 | `communication_permissions.py`、`communication_management.py` | Client-origin、Root↔Route 收发与管理继承；普通 Agent 管理被拒绝 |
| R06 配置时接入 | `communication_management.py`、`runtime_deployment/receiver_codex.py`、`receiver_opencode.py` | 实际 Factory Session、远端配置返回真实 Session；无 Provider 不伪造 |
| R07 一个通讯录 | `communication.py` 的 `list_collaborators` | 真实默认联系人、可选过滤和稳定引用；权限内选择，显示名不作为路由身份 |
| R08 单一配置 | `communication_management.py` | 六项真实 PG 并发测试：属性合并、冲突拒绝、改绑及准备期间变更；实际远端正常采用 |
| R09 统一自然消息 | `communication.py`、`communication_tools.py` | 普通/Client 发信及回复；空文、非法目标、伪造参数拒绝且无消息副作用 |
| R10 原文与第三方 | `communication.py`、`communication_schema.sql` | 原包不覆写，第三方不能代答私信，回复作者/目标必须准确；自然更正作为新消息 |
| R11 激活与等待正交 | `communication.py`、`communication_dispatch.py` | 默认 invoke+async、message_only 无 Native、message_only+sync 等主动回复 |
| R12 主动精确回复 | `communication.py`、`communication_replies` 索引 | 正确 B 回复与错误作者/目标/引用、Native final 配对；实际 B 自主 MCP 回信 |
| R13 多项关系 | `communication.py` 的 send/wait | 同对端多引用、any/all、重复等待取得同一首条回复；不额外发信或唤醒 |
| R14 双向 sync | `communication.py`、`communication_dispatch.py` | B 先提交并解除 A 等待，再观察自己的新请求；活动 Tool Result 不另开重复 Native |
| R15 分别持续 | `runtime_tests/test_communication_restart.py`、`communication_dispatch.py` | 实际 MCP 等待进程被终止，新进程从原引用接续；原消息/回复和防重保留 |
| R16 超时不撤回 | `communication.py` 的等待 | 超时后晚到回复及新实例继续观察；没有文本触发的 stop_wait 或撤销 B 工作 |
| R17 Inbox 视图 | `communication.py`、`communication_schema.sql` | 权威 packet 与派生消息/回复索引；两个实际 stdio 入口收发，普通读取不消费 |
| R18 安全入口 | `native_delivery.py`、Driver、默认维护器 | 实际 idle Native；受控 busy 退避、持久 Inbox 和活动等待入口；未验证 Hook/steer 不承诺 |
| R19 可查历史 | `communication.py`、`project_archive.py` | 原文反复读、旧包不消费、断线补读、真实权限重验 |
| R20 稳定分页 | `communication.py`、`project_common.py` | 事务提交顺序锁、筛选绑定游标及受控交错；正文 UTF-8 字节续读 |
| R21 最小 Native | `native_delivery.py`、`receiver.py`、Native Drivers | 真实一次发起；消息链和通知链不启用 terminal collector，也不投影为回信 |
| R22 同请求防重 | `project_service.py`、`communication_dispatch.py`、Node Journal | 原键重试、同键异文拒绝、独立同文保留；Native 未知不盲重，新连接须保留显式原键 |
| R23 持久与未知 | `communication_dispatch.py`、`delivery_operations.py` | 默认入口真实维护、四项并发界限、异常隔离和预算、ACK 未知仍可收到真实回复 |
| R24 纯状态 | `communication.py` 的 `list_harnesses`、receiver health | 实际 Session 只读观察；离线/未知不 prepare，读回失败不冒称不存在或已就绪 |
| R25 有限上行 | `communication_faults.py` | 受控直接上级、上级不可达才逐级、busy 延迟、未知不重放、顶层保留；不判断排障业务完成 |
| R26 事实与继续 | `project_service.py`、`communication.py`、`communication_management.py` | 提交后观察失败仍返原引用；配置提交/准备分开；回复续读动作保留明确关系 |
| R27 有用上下文 | `native_delivery.py`、`project_mcp_server.py` | 原生上下文标明 ACS 身份、原文和 reply/read 动作；真实同名工具误选后改进并重新跑通 |
| R28 文件来源 | `project_source.py`、`filesystem_gateway.py` | 现有 Source 精确版本、机器连接/OS 路径与范围授权；正文路径没有复制或 Git 副作用 |
| R29 自然交接 | `communication.py`、普通 send 工具 | 目标/资料位置作为原文；无任务交接生命周期或固定业务字段 |
| R30 最小存储 | `communication_core_schema.sql`、`project_schema.sql` | 新装从 82 表减为 46 表；保留 Outbox、技术尝试、回执与关键防重索引，无固定清理 TTL |
| R31 安全过渡 | `communication_storage.py`、`communication_archive.py` | 已知 LF/CRLF 采用、未知指纹/缺账本拒绝；原始旧行不改、关联不足不猜；真实 pg_dump/restore 隔离演练 |
| R32 合同一致 | `communication_tools.py`、公开 JSON 目录、MCP 入口与技能 | 当前实际导出、默认/空值、权限和结果版本核对；当前 README 区分候选与旧 Release |
| R33 内容无控制权 | `communication.py`、可信 caller 配置、receiver auth | 正文角色不提权、任意 sender 参数拒绝、系统包不能由普通 Agent 署名；Host 控制留给 Harness |
| R34 受控资源 | `communication.py`、默认维护器、Source/文件限额 | 列表/正文/通知/租约清理有界，四项投递并发、公平独立目标；没有牺牲消息或权限来提速 |

## 可独立复核的证据

- [初始 WP00–WP06 增量](../../integration_evidence/acs-communication-20261031/REPORT.md)：
  早期独立 Codex A/B、身份、关联、等待、历史与权限；其中“尚未完成”是该时点记录。
- [任务运行域退出](../../integration_evidence/acs-retirement-20261031/REPORT.md)、
  [最小存储与恢复](../../integration_evidence/acs-storage-20261031/REPORT.md)：
  当前入口无 Work、已知采用/未知拒绝、真实恢复演练与新装候选。
- [等待进程中断](../../integration_evidence/acs-restart-20261031/REPORT.md)：
  实际进程/数据库恢复，明确脚本 Agent；当时源码外发授权问题已由后续用户授权解决。
- [物理签名 Native](../../integration_evidence/acs-remote-native-20261031/REPORT.md)、
  [默认入口维护](../../integration_evidence/acs-maintenance-20261101/REPORT.md)：
  独立 Windows Codex/OpenCode 与正式接收工厂，以及默认入口零评测器派发。
- [长正文继续读取](../../integration_evidence/acs-content-20261101/REPORT.md)：
  PG 正反例与一个真实 Codex 读取者；脚本 B 不能算第二个模型。
- [配置绑定一致性](../../integration_evidence/acs-configuration-20261101/REPORT.md)：
  六项 PG 竞态、当前源码双模型、安装候选；887 组件通过/729 跳过。
  首次取消并发测试失败、同源码复测通过及根因未定位的事实全部保留。
- [核心交付复核](../../integration_evidence/acs-core-audit-20261101/REPORT.md)：
  当前公开说明、声明的 CI PostgreSQL 范围、工具链、隔离安装器以及干净
  checkout 测试输出/主机状态夹具修正；各次失败和复测分别保留。
- [已安装服务主链](../../integration_evidence/acs-installed-native-20261101/REPORT.md)：
  实际 console 启动、独立 Linux Codex/OpenCode、一次默认投递和主动回复，
  退出后安装完整性；篡改拒绝反例与未通过的 Windows localhost 路径单独保留。
- [v2.1.0 资格](../../integration_evidence/acs-qualification-20261101/REPORT.md)：
  反向物理 Native、OpenCode Shared、空闲生命周期及 Linux 600 秒负载。
- [v2.2.0 Codex Shared 与 Windows 负载](../../integration_evidence/acs-codex-shared-20261101/REPORT.md)：
  真实 Codex Shared 独立模型闭环、OS 边界、精确源清单和持续负载复核。
- [恢复与生产升级](../../integration_evidence/acs-recovery-20261101/REPORT.md)：
  生产服务、版本与数据保留的独立验收范围。

各报告保留对应源清单、实际命令、版本、失败和证据层次；后来提交不追改
早期实验的源版本，也不把全部历史目录合计为当前候选测试数。

## 仍未由这些证据证明的范围

完整跨 Harness/权限/主机组合矩阵、Windows Shared Native、真实模型的全部
故障替换窗口、更大规模或长时间运行以及模型吞吐 SLA 仍需单独验证。
Windows 早期偶发超时的根因归属不由后来通过的复测推定。
正式生产清理、不可逆迁移、远端环境切换和公开发布遵守各自授权边界。

R01–R34 的代码机制已有对应定位，工程完成判断仍须结合所声明环境的运行证据。
本记录不把支持范围之外的场景回填为通过，也不扩入长期 RSI 研究。
