# ACS 通信故障通知与安装验证

本地工程提交：`40ea9c108d2eac698754cc42da842679af9ceeb7`。
分支 `codex/core-cleanup`，基线 `03193767632daf5191eef8435cd32d4f5c4bc8a7`。
完整目标仍为 active；本页记录本轮实际交付，不能代替全部 WP00–WP06 验收。

## 本轮实现

- R25：`communication_faults.py` 保存实际配置者的直接管理关系。局部改名和
  属性更新保留该关系；联系人和配置结果返回真实 `manager_handle`。
- 通信障碍以 `acs-notice/1` 系统来源经既有 Dispatcher、NodeJournal 和
  NativeDeliveryAdapter 发起管理者。系统通知不进入 Agent 消息/回复索引，
  不携带原私信正文，不解除原发送者的回复等待。
- 管理者明确不可达才继续向其实际管理者上行。busy 等待同一通知；可能已经
  Native 时保留 unknown，不重放或自动唤起父级。原消息 ACK 未知也只保留通知。
  最高层 Client 使用自己的 Inbox。没有修复任务、质量验收或故障业务生命周期。
- R26：通知读取返回原障碍和通知自身 Native 投递状态。真实模型误将通知引用
  填进 `check_inbox.with` 后，补齐 `read_message`/通知说明及安全的字段纠正提示；
  无效过滤继续拒绝，未放宽读取权限。
- 身份边界：原始自然包也检查精确 Grant 与作者绑定。Native 派发检查接收身份
  撤销；`message_only` 可以留给稳定 Slot，重新授权后仍能读取。
- 存储采用：新增独立的 `communication_notice_schema.sql`，显式采用保留既存
  消息/通知。四份 Project/通信 SQL 使用 LF 规范校验，只识别同一 SQL 的已知
  LF/CRLF 形式，未知版本或内容仍拒绝。服务启动不自动迁移生产数据库。

主要文件：`runtime/communication_faults.py`、`communication_dispatch.py`、
`communication_management.py`、`communication.py`、`delivery_models.py`、
`delivery.py`、`native_delivery.py`、`project_service.py`、`mcp_runtime.py`、
`communication_tools.py`，以及对应测试、工具合同、CI 和通信说明。

## 实际证据

| 范围 | 结果 | 证据 |
|---|---|---|
| 核心通信、通知、权限、HTTP、等待 | 89 passed / 5 skipped | `notices-verified.xml` |
| 共用投递、Codex/OpenCode Adapter、Driver 回归 | 190 passed / 12 skipped | `notice-delivery-regression.xml` |
| 工具/技能合同 | 15 passed | 实际 unittest 运行；不是模型验收 |
| Windows 真实管理者 Native 通知 | 1 passed，66.450 秒 | `native-notice-current.xml` |
| 最终冻结源码真实 Native 复验 | 1 passed，172.256 秒 | `native-notice-frozen-retry.xml` |
| 新环境安装后的公共工具 A/B 闭环 | 2 消息、1 主动关联回复、0 WorkItem/AcceptedState | `notice-wheel-install-current.json`、`installed-communication-smoke.py` |

最终真实模型目录：`notice-f865e8bd5360/`。A 与管理者 B 为独立、分别认证的
真实 Codex 上下文；C 的 pre-call 拒绝是明确的受控故障注入。正式通信维护循环
发起 B 的第一轮，B 自己调用 `read_message` 取得 ACS 通知状态。实际一次
`turn/start`、一次管理者读取、原消息无 Agent 回复、WorkItem 为零。
评测器没有代转正文、代造回复或把 Native final 投影成回复。

Native 为 Windows Codex `0.166.0-alpha.5.1`。凭据按用户明确授权仅用于隔离
子进程的已有第三方 Provider，未写全局配置或凭据文件。A/B 均使用独立
CODEX_HOME、关闭 Apps/plugins、仅接入测试 ACS。

`source-files.json` 记录运行源码逐文件哈希；测试核对运行中源码未变。
wheel 的 109 个运行文件与真实 Native 源码逐一一致。安装烟测在新环境的
`site-packages` 导入实际 wheel，并使用真实 PostgreSQL/正常公共工具；该烟测
没有请求模型，不能代替真实 Agent 验收。

本轮修改文件 Ruff、编译和 Git whitespace 检查通过。扩大的全目录 Ruff 仍有
7 项既有诊断，已核对对应文件相对原 HEAD 未改，未把它计为全目录通过。
HTTP 回归保留 SDK 的订阅弃用警告。

## 保留的失败与纠正

- `native-notice.xml`：验收快照撞上 Codex 首次写入时空 rollout，随后改为读取
  实际工具完成事件。`native-notice-final.xml`：事件缓冲未排空；修正观察器。
- `native-notice-verified.xml`：模型只使用内联通知，未查实时状态；
  `native-notice-live.xml`：模型用了错误过滤字段。补充正常任务的实时状态目标，
  并修正工具说明和字段指引后，取得上文真实工具读取通过。
- `notice-core-current.xml` 暴露接收撤销对纯 Inbox 留信的过度限制，已修正并
  通过 46 项通知/HTTP 权限回归。`notices-integrated.xml` 暴露不同 Schema 的
  测试共用逻辑 Tenant/Slot 而竞争数据库级锁；夹具采用独立 Tenant，断言保留，
  最终 89 项通过。
- `native-notice-frozen.xml`：模型连接中断，A 尚未调用 send，管理者 Native
  调用零次；不计通过。一次有界重试取得最终冻结源码通过。该 Provider 存在
  传输波动，两个真实场景耗时不能视为 ACS 派发延迟或性能承诺。

失败 XML 和完整本地原始日志均保留，未改弱成功判据或删除失败证据。
生成 XML 保留 traceback 自带空白，Git 属性仅将这些生成数据排除空白样式检查；
源码检查仍启用。

## 候选、仓库与继续工作

本地候选：`dist/candidates/acs-communication-40ea9c1/`，包含实际验证的 wheel、
工具/技能合同、通信说明和候选清单。wheel SHA-256：
`126da78dea2c15bffef8ad836914e9c9afe772ca91885d325eba1128c12a9537`。
这是开发候选；包内 `0.1.0` 来自当前 pyproject，开发包 v2.33 不是软件版本。

用户原有两份 README 的字节哈希已核对保留；原有 `.git-rewrite/`、开发包和
`docs/client/` 均保留。源码提交与证据分别记录，无 Push、标签、正式发布、
生产数据清理或远端环境切换。当前工作区后续会话无需同步；远端克隆未更新。

下一切片继续 WP05 的真实依赖盘点与隔离备份/前向修复演练；结合实际依赖
补足 Slot 接收环境采用和 WP06 矩阵。跨机器、真实 OpenCode 模型互通、Owner
故障矩阵、重启恢复窗口、延迟/资源分项、生产存量迁移与正式独立审查仍需证据。
旧任务表/库代码仍有历史读取和结构依赖，未声称物理清理完成。
