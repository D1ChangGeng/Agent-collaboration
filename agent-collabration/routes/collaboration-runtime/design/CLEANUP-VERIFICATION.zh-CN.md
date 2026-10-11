# Owner 协作实现与验证记录

日期：2026-10-12。源码候选：`codex/core-cleanup`，起点 `e208a44`。

## 实现范围

| 清单 | 实现 | 主要验证 |
|---|---|---|
| A01–A04、A08 | 持久安装者身份、实际对象校验、按实现发现工具；共享策略独立保留 | owner access、Project、Source、Domain PostgreSQL 回归 |
| A05–A06 | Team 配置使用成员、职责、Harness；owner 恢复遵循持久工作意图 | 最小 Team、旧预算之后恢复与单次投递 |
| A07、T07 | 历史形成事实与当前决定独立，保持候选和 Reviewer 独立性 | enrollment/evidence/Review PostgreSQL 回归 |
| T01–T04、T10 | Node、Runtime、Connection、Endpoint、内部密钥持久登记；真实签名、去重与明确撤销 | 过期登记后的真实 PG/TLS、Node 登记与撤销 |
| T05–T06 | 普通命令与 Message 的业务期限可省略；明确业务期限单独处理 | send/wait 与 owner deadline:null 回归；实际无期限远程任务 |
| T08–T09 | 通知跟随实际连接；原生就绪按实际状态判断 | 原窗口之后通知、Session 替换、实际 idle 读回 |
| T11 | 原 Attempt/Dispatch 结果持久保存、签名分块回传、历史结果视图 | 完整 SHA-256、重复读取、篡改拒绝、两次新会话恢复 |
| H01–H09 | 选择的 Codex/OpenCode 配置、模型、工具及环境生效 | Driver 协议回归；1302-1 个人 Codex 实际 Shell 读取 |
| H10–H11 | 原生会话操作与精确所属控制；普通进程管理 | POSIX 实际进程组、Windows 真实 JobObject 与终止读回 |
| R01–R04 | 职责、业务对象、Source 工作区视图及故障原因分别表达 | Project/Route/Work、dirty workspace、历史与业务期限错误回归 |

## 验证结果与适用范围

- Linux Runtime 全量：1370 通过，33 项按平台/环境跳过。
- 后续受影响路径：100 通过，1 项跳过；最终 owner 历史/恢复/重试：11 通过。
- 通知、会话恢复、Source 与签名结果回传：13 通过。
- 1302-1 的最终 systemd / Host Node：50 通过，2 项跳过。
- Windows 实际 JobObject：8 通过，1 项跳过。
- Windows 安装、自动升级、启动恢复、发行与 Skills 合同：58 通过，18 项平台跳过。

以上结果具有各自的运行源码与场景范围；全量结果早于最后的恢复/历史改动，
后续改动由对应路径回归验证。Fixture 提供的原生回调保持 component 范围。
历史 P1/P2 Gate 保留其原始绑定。

## 现有安装读回

Core 与 Receiver 使用同一候选 wheel：
`7d2ea3ef6f290022bdc1bb746fada81cd5c69e976fd866831e86fc07a9c0a804`。
各端安装清单与 107 个文件完成校验，原目录和配置备份保留。

Core 的 17 条身份、2 个 Node 绑定、2 个 Runtime 及 11 个资料配置保留。
Receiver 使用已选择的个人 Codex 环境；实际源码 checkout 仍为 `e900773`。
Root、Route、Node、密钥、既有 journal 与结果归属保留。

实际协作读回包括：

1. 本机标准 MCP 创建工作，异步发送、相同请求重试，普通业务期限为空。
2. 1302-1 使用原生 `awk` 读取 README，形成最终结果。
3. 两个新 MCP 会话从 Inbox 与结果 handle 读取相同内容。
4. 现有 ChatGPT 私有连接创建工作、派发远程任务并读取最终内容。
5. Receiver 受控停止后，Core 调用已配置的准备入口恢复为实际 `idle`，
   服务重新变为 `active`，Endpoint 登记保持同一修订。

Windows、WSL、1302-1 的 setup 与八个知识 Skills 已更新并核对摘要。

## 候选提交与集成验证

实现提交 `28a829ad7d29b2ea5d8dae17651bd0c2930fd977` 已推送到
`codex/core-cleanup`，并建立
[Draft PR #12](https://github.com/D1ChangGeng/Agent-collaboration/pull/12)。
私有八模块知识插件已保存为 v0.1.1，账户中 35 个文件与审查包逐项一致。

首次 GitHub CI 的三个 Python 版本校验与 Runtime 组件测试通过；
PostgreSQL 集成组合运行中，12 个 owner 场景在 setup 阶段缺少共享
`project` fixture。相同收集顺序在本机复现。共享测试入口提前注册原有
fixture 后，这 12 个场景通过，原有断言保持。最终 CI 读回继续跟随
包含此测试入口修正的候选提交；生产 Runtime 与已安装 wheel 保持相同。

## 客户端元数据迁移

当前 ChatGPT 连接缓存旧 schema，仍要求 budget/deadline/wait timeout。
此次网页执行使用明确一小时业务期限以验证现有连接的真实写入与回传。
Owner 服务器公开的 schema 已将这些字段设为可选。

最终客户端步骤为：打开现有 ChatGPT Plugins 连接，选择 **Refresh**，
确认工具定义更新并开启新会话。随后复核省略这些字段的调用。
参见[官方元数据刷新步骤](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata)。

外部浏览器自动化因宿主无法可靠识别当前 URL 而停止。
此客户端刷新与 GitHub CI 读回分别记录；候选提交与 PR 保持可审查状态。
