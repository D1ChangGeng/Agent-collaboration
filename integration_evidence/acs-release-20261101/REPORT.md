# ACS 2.0.0 整合与生产升级准备

工程基线 `5af3e63e584ea9c3b9b15da2b9cc6b714f993dcd`，整合已发布 main
`de3aa5ac4634ed6467dd9bb44db39a487fbeb3ad`（v1.6.0）。隔离工作树分支为
`codex/communication-release`；原工作树和用户 README 增补保留。

## 实际实现

- 保持通信核心和任务域退出；合入 v1.6 的当前机器文件管理、项目配置、
  Windows/WSL 登录恢复和 Docker 后端诊断。旧任务可选源码功能不恢复。
- Owner 项目上下文读取当前机器文件；Source 归档必须给出明确 source/revision。
  当前项目位置可配置；Shared 和普通 Agent 不获得该配置能力。
- 修复普通 Owner Agent 的项目目录越界可见性：只有受信 Client 可以使用全局
  Owner 目录，绑定 Agent 仍按项目成员关系列出。新增隔离和管理拒绝反例。
- 精确接受发布 v1.6.0 的 Core 1.14 与 Project 1 指纹（LF/CRLF），保持未知
  指纹、缺账本和缺防重索引拒绝。正常启动不迁移，不删除旧表或改写旧作者。
- 产品版本为 2.0.0；旧自动更新保持主版本边界。更新 Bootstrap 默认、CI 构建、
  工具目录 11、公开用法、升级说明与 setup 指引。软件版本与 setup 0.4 分开。
- 发布检查不再固定 v1.0.0、PR 1 或历史分支；绑定当前选择的提交、PR、CI、
  完整归档摘要，拒绝未完成/失败 CI 与覆盖已存在的发布。

## 已运行验证

| 范围 | 结果 | 材料 |
|---|---|---|
| 默认完整组件 | 887 passed / 745 skipped，162.57 秒 | `linux-5542a4658d1041eab686484c40273080.xml` |
| setup/启动/发布工具链 | 255 项，0 失败，3 跳过 | `unit.stderr.txt` |
| Gate 工具链 | 123 项通过 | `gate.stderr.txt` |
| 当前文件、明确归档版本、配置限制 | 10 passed | `linux-cbb5c49e06574afb92d2bb69d7179270.xml` |
| 1.14 LF/CRLF 迁移与保行/防重 | 2 passed | `focused.xml` |
| 普通 Owner 目录隔离及配置拒绝 | 1 passed | `focused-1e9a17ce36d64c18bad321e0867689a7.xml` |
| 完整 PostgreSQL 门禁首次 | 369 passed / 3 failed / 8 skipped，351.82 秒 | `linux-ed4695b816e04f5eb02f7f4094377bec.xml` |
| 历史基线/Owner Route 邻近复核 | 7 passed | `linux-f30c5be595cd4d8dbf52709280b6e2f0.xml` |
| 发布 CI 绑定反例 | 4 passed | `tests/test_release_preflight.py` 实际 unittest |
| 2.0.0 wheel 真实 provisioner | 107 个 Python/SQL 文件逐字节匹配 | `receiver-install.json` |
| 实际已安装 2.0.0 独立 Codex/OpenCode | 1 passed；2 Message/1 主动回复、1 次默认 Native 发起、ACK 确认；无终态/SSE | `linux-codex-5d1ab4a981d84ef9b18a132b0432f231.xml`、`native/` |

组件/工具链是本机隔离 Linux 执行，不等于 GitHub 托管 CI。跳过项不计能力
通过；实际模型与生产切换各有独立证据。

完整 PG 首次的三个失败是 main 更新了已经冻结为 1.13 的历史任务夹具期望，
以及新增的已撤回任务可选源码测试要求 NULL；不通过恢复运行时任务对象修复。
冻结夹具保留原版本，真实 1.14 过渡由新迁移测试和实际存量还原演练验证。
之后的 7 项复核保留原断言。初次 Windows 目录/归档探针因换行读取方式和
平台能力失败，当前文件测试按真实字节断言，并在支持的 Linux 后端运行。
一份最早 focused XML 被后续复核覆盖，不能当作已保留的首次原始记录；后续
结果文件均采用唯一名称，现存失败 XML 保留。

新的实际模型运行使用已安装 2.0.0 console entry 与普通独立 MCP 身份。评测器
派发次数为 0，模型阶段 72.12 秒，退出码 0、自有进程组为空；运行后安装清单
完全一致、字节码为零。源码与 wheel 对应，详见 `native-summary.json`。

## 实际存量演练与授权边界

用户已明确选择同时升级 WSL Owner 服务与 1302-1 接收节点，并授权 GitHub
产品发布。切换对象按实际安装记录绑定；没有由 SSH 别名推断额外目标。

对实际 WSL v1.6.0 / Schema 1.14 以只读一致性快照备份，备份及私有配置留在
同一账户 0700/0600 的备份目录，不进入 Git 或模型上下文。还原仅发生在专用
测试容器的唯一新库。74 张原表数据摘要完全一致；迁移事务回滚恢复原行和
Schema，提交采用后全部原行保留，新增 8 张通信表。没有重建身份或启动 Native。
参见 `production-rehearsal-d78f08bba0634276a316136f765691b5.json`。

生产 WSL/1302-1 仍在原版本，尚未写库、重启或切换。节点原私有入口依赖旧
Collector 内部字段，不能直接继续用于新内核；将以保留 Node 身份、签名键、
Journal 和实际下一端点版本的正式接收器入口替换。发布、生产切换和实际客户端
验证必须另行记录结果，不由本准备报告冒称完成。
