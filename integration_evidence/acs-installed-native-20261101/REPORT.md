# 已安装 Receiver console 与独立 Agent 主链

接续 `ca3b3971b24c9f4c39f79bb58ea6499bb896c54b`，分支 `codex/core-cleanup`。
本阶段补足已安装服务与源码装配之间的验证缺口，主要核对 R06/R08/R18/
R21–R24/R27/R32。Runtime 的 106 个 Python/SQL 文件未修改，实际运行已有
候选 wheel `8d9a9f6578ff23d4898a2bc77da46b10f862ce7b2b6a044c0f3cdb89a1197eaa`。

## 实际改动

- `test_communication_installed_native.py` 新增显式 opt-in 的实际安装用例。
  复用原签名接收、普通身份和主动回复判据，区分 Windows→WSL、本机 Linux
  与原物理 SSH 主机，不把同主机实验描述为物理跨机。
- 现有 `test_communication_remote_native.py` 复用受权控制通道，并支持本地
  Linux/WSL；Windows 路径使用正斜杠传递，Linux 的调用端配置收紧为 0600。
- `fixtures/remote_native_receiver.py` 从真实安装 console 取得 Factory 绑定，
  以子进程直接执行 `acs-receiver --config`，不在测试器内代替装配 server。
  健康经 TLS 指纹核对；实际 Journal 统计 prompt/终态读回/事件订阅；退出
  使用该 console 的正常 SIGTERM 处理，再核对已记录 PID/birth 和自有进程组。
- B 的测试专用 Python MCP 包装器在 import 前关闭字节码写入，遵守 Receiver
  安装的不可变清单。没有删除额外文件或放宽完整性、授权与投递断言。
- 公开通信说明和支持矩阵增加精确的实际安装范围及失败路径。

## 真实运行结果

| 范围 | 结果 | 证据 |
|---|---|---|
| 真实 console 生命周期，无模型 | 1 passed，58.59 秒；真实 Session、签名配置读回、正常退出及空进程组 | `lifecycle-3d7693a034bc4ae0add1f22cce77d315.xml`、`lifecycle/` |
| 实际安装服务与独立 Linux A/B | 1 passed，201.63 秒 | `linux-codex-266ab714a33c4558b541777d53dd033e.xml`、`linux-model/` |
| 运行后安装完整性 | 106 文件对应候选、清单与运行前一致、0 个 pyc/额外文件 | `install-unchanged-after-model.json` |
| 独立篡改安装反例 | console 在读取配置/Native 前拒绝，正常主安装不变 | `entry-tamper-rejection.json`、对应 stderr |
| 默认环境不自动调用模型/外发源码 | 5 skipped，明确 opt-in | `optin-default.xml`；不计功能通过 |
| Ruff 和差异检查 | 通过 | 三个改动测试文件，无 Runtime 源码变化 |

最终主链在 WSL 内直接访问隔离 PostgreSQL。A 是真实 Codex 0.146.0，B 是
正式 Owner Factory 启动的 OpenCode 1.18.34。两者是独立模型上下文、不同普通
身份，各自用自己的正常 ACS MCP 工具。B 标签仅交给 B；评测器没有转发输入、
提供回复 ID、调用派发器或将终态输出合成回复。

Authority 核对为 2 条 Message、1 条准确关联回复，Work 表不存在。默认 stdio
维护器完成 1 次尝试，最终 delivered/runtime_acknowledged；实际 prompt_async
为 1，评测器派发次数 0。Native Journal 终态读回与 SSE 订阅均为 0。
配置结果的 Session 与真实 Native 读回一致。模型阶段 167.15 秒包含模型和
网络；201.63 秒是整个测试，不当作 ACS 传输延迟或性能 SLA。

正常 console 退出码 0，Native 自有进程组为空；范围为 owned_process_group，
不是 subtree containment。退出后真实 `--verify-install` 返回与运行前相同的
完整清单，106 个文件仍对应同一候选，没有额外字节码。安装/解释器是实际
provisioner 及受支持的摘要绑定依赖 wrapper，具体目录和哈希见 `receiver-install.json`。

## 保留失败与原因边界

- 首次 Windows→WSL 路径反斜杠被 shell 解释，未启动接收器；改用正斜杠。
  对应 `lifecycle-4eae53e69fbb4fcab2c5782d19a5e8c6.xml`。
- 两次 Windows→WSL 模型尝试在本机测试数据库连接时异常关闭，分别发生于
  观察查询、端点绑定查询；不计通过。数据库容器启动时间未变、无重启/OOM，
  后续普通连接可用，但根因没有确立，不说已修复 Windows 转发。原始 XML、
  `first-model/` 和 `second-windows-model/` 保留；没有放宽查询或消息断言。
- 首轮测试 MCP 包装器生成 50 个 pyc，完整性校验正确拒绝额外文件，Python/
  SQL 原内容未变。`first-install-bytecode.json` 保留；旧安装未清理或改清单，
  后续从同一 wheel 新建安装并修正包装器，最终运行后再校验。
- Linux 首次 A 的 MCP 握手失败；其测试配置默认 0644，与服务的 0600 约束
  不符。收紧配置后，MCP 握手及实际独立交流通过。保留首次 XML 和
  `linux-first-model/`，没有放宽私有路径检查。
- console 日志保留 TLS 探测连接关闭后的 BrokenPipe 诊断；实际主链通过。
  不据此宣称所有故障窗口、平台版本或日志行为均已资格化。

各实验保留各自源码清单；最终 108 文件与当前源码匹配（106 Runtime 文件加
两份测试控制源码），外层新增用例也在对应 Linux 源快照清单中。
私有配置、密钥和模型推理不归档。独立判据与真实模型结果分别记载。

## 支持边界与后续

这补足同一 Linux Owner 环境的实际安装 console 主链。既有 Windows Codex→
1302-1 OpenCode 物理方向保留其原始源/版本证据；本阶段没有把未通过的
Windows localhost→WSL 路径变成通过，也没有证明反向物理 Native、Shared
OpenCode、Systemd 受限 Profile、所有故障替换或大规模负载。

核心实现和声明范围见 [通信支持记录](../../docs/runtime/COMMUNICATION-STATUS.md)。
后续扩大平台声明需对应资格验证；生产清理、不可逆迁移、正式服务切换和
发布仍需各自授权。本阶段没有 Push、切换远端正式 checkout 或修改用户默认配置。
