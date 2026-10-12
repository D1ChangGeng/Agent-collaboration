# Source 选择与读回验证记录

## 候选与基线

本记录覆盖产品 Source 默认选择、当前工作树读取、显式快照身份，以及
对应的构建、双主机安装和知识同步。每项结论保留其测试阶段和运行前缀。

| 项目 | 已确认状态 |
|---|---|
| 分支 | `codex/core-cleanup` |
| 基线 commit | `e0b76e9aebf9a7d6eee7dce52e70a6b23cb61107` |
| 基线 tree | `7d6306724a5ab827250b8e10af746179154a3c2e` |
| Source 候选 | 本记录留存提交前冻结验证；提交身份与后续读回见关联 PR |
| 评审入口 | [Draft PR #12](https://github.com/D1ChangGeng/Agent-collaboration/pull/12) |

基线 tree 标识已提交基线；Source 候选的改动、包指纹和安装文件清单分别
记录其实际状态。用户已有 README、客户端文档和本机数据沿原归属保留。

## 产品行为与读回身份

产品默认 Source 为 `source-local`，首选仓库读取位置是
`/mnt/d/Chatgpt/Agent-collaboration`。当前读取解析该仓库的物理主工作树，
观察实际检出的分支和当前编辑。SourceBinding 提供仓库、位置与版本建议；
Agent 根据实际可用的 Native、Git 或外部仓库 MCP 选择读取工具，并记录
它真正读取的 provider、仓库、分支、commit/tree 和 workspace 状态。

产品源码观察与 Management Root 观察分别记录。实际读回携带
`actual_source` 的 provider、root、commit、tree、view_revision 和
observed_at；`current_readable_root` 描述 Core 文件系统位置，
`origin_hint` 保存来源 host/path 的参考信息。显式 revision 保留已捕获
快照的字节与身份，分页沿该 view_revision 稳定继续。候选、Review 与
接受状态采用实际读取和产出的证据身份。

真实 Git/DrvFS 的 index 短读路径已修复。正常 Git 临时对象按其暂存性质
处理。源码内容和 diff 使用配置的 Artifact 容量，metadata 预算独立
约束其元数据。实际产品 Scope 的容量配置保持 `256 MiB`。

## 测试范围

| 验证阶段 | 结果 | 适用范围 |
|---|---|---|
| Source/Scope 相关选择 | 76 passed | 在最终临时对象、内容容量和显式快照身份修复之前 |
| 最终 Source 模块 | 45 passed | 最终代码的 Source 模块路径 |
| 最终 owner Source PostgreSQL | 11 passed | owner Source 与真实 PostgreSQL 路径 |
| Ruff F | passed | 静态 F 规则检查 |
| Skill validator | passed | Skill 与引用结构检查 |

三个测试选择存在重叠，按各阶段独立引用。最终模块和 PostgreSQL 结果
支持各自实际执行的路径；部署与 MCP 行为采用下面的单独读回记录。

## 真实 stdio MCP 验证

完整 stdio MCP 检查在先前 Source 行为等价的 wheel 上执行，其 SHA-256
前缀为 `9de445`。该运行先于最后两行显式快照身份修复；最终包的安装
指纹和最终前缀重复读取属于后续独立证据。

该次真实检查确认：

- 服务暴露 37 个工具；四个 Source schema 的 source_id、source_root、
  revision 为可选选择字段。
- 省略选择字段的读取返回真实 Native README，内容 SHA-256 为
  `9e1341285d25c806289c6a652c6912f7a6f2a629a8998a5a780318309565796c`。
- 默认产品读取的实际 commit 为基线 `e0b76e9`，Management 观察单独记录。
- 显式读取复制的源码 checkout 后，再省略选择字段时恢复到默认物理
  主工作树。
- 实际结果报告读取 provider、root、commit/tree、view 和观察时间。

最终 `source-identity` 前缀的默认读取复测安排在 Source 候选提交之后，
其结果跟随 Draft PR #12 追加读回。

## 最终包与双主机部署

| 项目 | 已确认读回 |
|---|---|
| 两主机 wheel SHA-256 | `fbabcd2204e49ab9a4c5a3838ea9541963dbd78af64cd6955d80bf9b22f0f289` |
| Core 前缀 | `manager-core-cleanup-source-identity` |
| Receiver 前缀 | `receiver-core-cleanup-source-identity` |
| Core 安装 manifest SHA-256 | `f9869e8bbb83e36f28db20625428c7fcaf703eee1a5926825f2d4b85b7c17cc9` |
| Receiver 安装 manifest SHA-256 | `7675afc3a2f1477b948e3e7a72d51d14ffe30a640e22749e982373d42911e129` |
| 安装文件读回 | 两主机各 107 个文件通过核对 |
| Endpoint 与 Message binding | revision `781` |
| Receiver | `idle`，native Codex `0.155.0` |
| Native checkout | `e900773`，保持原状态 |

原密钥、Native 环境选择、journals 和备份保留其身份。包指纹与安装文件
读回证明该最终包已部署到两主机；此前完整 MCP 运行保留其原 wheel 和
阶段范围。

## 知识模块与私人插件

Source Skill 四个文件已在 Windows、WSL 和 1302-1 核对，文件集合 digest：

`cecac6467346802f85b50ab9c18b0c0249ba59403f833d7a275fd0a485e375e5`

私人知识插件更新已在六文件独立 Gate PASS 后完成：

| 项目 | 账户读回 |
|---|---|
| 版本与范围 | `0.1.2`，`USER / PRIVATE` |
| Release | `pluginrel_6accb56b8dec8191b1d9fb31e9047ac5` |
| 文件总数 | 35 |
| 更新覆盖 | 6 个变更文件与冻结 overlay 精确匹配 |
| 原有文件 | 其余 29 个文件保持原值 |

插件账户读回、Source Skill 主机文件读回和 Runtime 部署分别保留各自证据。

## PR 验证与用户步骤

基线 `e0b76e9` 的 push 与 PR CI 的 10 项检查均通过。本记录覆盖
Source 提交前的冻结验证；具体提交、新 SHA 的 CI 与最终前缀默认读取在现有
[Draft PR #12](https://github.com/D1ChangGeng/Agent-collaboration/pull/12)
追加。正式 Runtime tag 和主 Release 采用独立发布流程。

ChatGPT 既有连接仍需用户打开连接、执行 metadata **Refresh**，并进入
新会话验证最小省略字段请求。当前浏览器 host URL policy 限制该页面的
自动操作，这一步保留为最小用户操作。此前 cached schema 下的真实
网页执行保留其原输入与验证范围。
