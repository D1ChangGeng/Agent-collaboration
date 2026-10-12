# 机器文件系统实现与验证记录

日期：2026-10-12。状态：Runtime、PostgreSQL、实际跨机器读回和安装核验已完成；
显式 Source 读取分组修订完成本机 Gate 与目录合同验证，其提交与 CI 读回沿
现有 Draft PR #12 跟踪。

## 产品与实现范围

Owner 文件工具直接操作所选操作系统账户允许访问的当前文件。
`read_file` 的必填参数为 `path`；机器与目录由会话选择或单次
`machine_id` / `cwd` 指定。隐藏、未跟踪、仓库外、二进制和大文件
采用相同的 OS 路径语义。`filesystem_context` 报告实际账户、主目录、
平台和目录；`select_filesystem` 保存当前 MCP 实例的选择。

Local、固定 SSH 服务和已登记 Node 使用可移植文件后端。Node 复用
Receiver 的 TLS、签名身份、持续 owner 授权、撤销检查和请求 journal。
文件服务直接处理请求，原生 Harness Session 有独立的执行状态。
Source 工具保留项目仓库观察与显式快照版本语义。

实现细节包括：

- 普通文件先在目标目录写好临时文件，再经 OS 替换；现有 mode bits
  按平台保留。符号链接和硬链接沿用本机打开语义。
- 服务进程对同一解析路径使用 OS 文件锁，锁随句柄关闭或进程退出释放；
  精确编辑在锁内读取和检查内容。
- `*** End of File` 补丁块匹配文件末尾，跨文件补丁报告已完成与待处理路径。
- grep 匹配和跳过文件诊断共同使用交付预算及条目限制，按游标续页。
- 远程修改派发后出现未确认的连接结果时返回 `write_uncertain`，
  下一步依据原机器文件与请求回执读回。

MCP input_schema 复用已有 owner 访问模式探测，再选择机器文件参数。
离线 catalog schema 探测独立于 Service/DSN 初始化，owner 文件参数与
shared/离线 Source 参数分别保持其适用的输入定义。

产品契约见 [机器文件系统契约](MACHINE-FILESYSTEM.zh-CN.md) 和
[工具使用指南](../../../../docs/runtime/MACHINE-FILESYSTEM.md)。

## 回归与独立复核

| 验证范围 | 结果 | 适用版本 |
|---|---|---|
| Linux 七模块 PG/TLS/Source/Project/HTTP 组合 | 100 passed，119.48 秒 | 原文件语义审计组合；服务进程 OS 锁由后续选择覆盖 |
| Linux filesystem/PG/TLS 三模块 | 19 passed，6.21 秒 | 原 OS 锁冻结实现 |
| Linux 最新 filesystem/PG/TLS/SendWait 四模块 | 30 passed，22.78 秒 | 包含离线 schema 兼容性修订 |
| Windows 原文件系统用例 | 13 passed，1 项权限场景按平台跳过，共 14 项 | 原机器文件系统实现 |
| Windows 最新离线 catalog 与文件系统选择 | 18 passed，7 项平台/PG 场景跳过 | 包含离线 schema 兼容性修订 |
| Setup unittest | exit code 0 | 原文件系统候选；执行记录未采集用例数量 |
| Skill validation | 通过 | 当前知识包 |
| 机器文件系统独立代码复核 | 全部 9 项修复检查 PASS | 原文件系统候选 |
| SCHEMA_FIX_REVIEW | PASS | 离线 SendWait schema、owner path-only、shared/离线 Source schema 一致性 |
| 最新本机完整 Gate tooling | 123 项用例，OK，15 项平台跳过，245.759 秒 | 显式 Source 分组元数据修订 |
| MCP catalog contract | 9 passed，0.005 秒 | 显式 Source 分组元数据修订 |
| CATALOG_FIX_REVIEW | PASS | 三项 Source 别名分组；既有 schema、Profile 与安全绑定一致 |

各运行按自己的模块与版本范围记录，数量按上述范围分别引用。
较早 Linux 93 项结果属于前期选择。既有 SendWait 测试保留原断言，
本修订通过最新四模块选择及独立 schema 复核。
历史 P1/P2 Gate 保留其原始输入、绑定和结论。

### 当前 CI 与 Source 目录分组

候选 `3fe5c3e9d762c39ff3c249073606d24254b15546` 的 CI runs
`38259317085` / `38259309928` 已确认三个 setup jobs 与 Runtime components
通过。Run `38259317085` 的实际 PostgreSQL 选择为 **360 passed、2 skipped**，
耗时 369.69 秒。

Gate tooling 的 Source 分组检查发现 `tool_groups.source_reads` 缺少已定义的
`read_source_file`、`list_source_files` 和 `search_source_files`。
本修订将三项读取工具加入既有 `source_reads` 元数据组。本机完整 Gate 与
9 项 catalog contract 验证结果见上表。

自有 Core catalog 已精确同步，SHA-256 为
`671b780a55a0a5c1fac6041a63deac05508d6b16de5ed4e01c8e1de4ea2ed111`。
此次改动范围是工具分组元数据；运行代码、wheel、工具定义及 Profile
沿现有已验证版本运行。本修订的 CI 读回绑定后续实际提交。

## 实际 MCP 与 SSH 读回

最新 wheel 的实际 stdio MCP 重复验证通过 **48 个工具**，
`read_file` 仅要求 `path`。两次 MCP 会话的机器与目录上下文互相独立。

| 实际路径 | 账户与场景 | 结果 |
|---|---|---|
| Core 本机 WSL | `d26fo`；合成隐藏文件、仓库外目录、write/read | 通过 |
| Node `1302-1` | `changgeng`；合成隐藏文件读取及精确编辑 | 通过 |
| 游标与文件动作 | 二进制字节续页、改变默认机器后沿原目标继续、glob/grep/patch | 通过 |

二进制页解码拼接的 SHA-256 为：
`1333fecd12640fb14a1602358f3e1ac54f39104ceed8f73e44b2e51d36dd337b`。

最新本机 README 读取单次实测耗时
`0.05162795199430548` 秒；该数值描述本次读取。
固定 SSH 服务此前已通过固定 argv、JSON stdin 读取真实远程 README 的实际验证。
上一 wheel
`8dad97729d3527ad1c28c7ec0e5a6ed8e6faf2b265f4977f581fa3605c553da7`
上的 48 工具实际旅程保留为该版本的结果，上一绑定修订为 783。

## 安装与运行身份

Core 与 Receiver 已安装同一最新不可变 wheel，各端 **113 个安装文件**核验通过。
Wheel 中的 **101 个 Runtime Python/SQL 文件**与当前冻结源码逐字节一致。

| 资料 | SHA-256 或读回值 |
|---|---|
| 最新 wheel | `b0f91e277cc6a77ea9a43694255ba8a5aafc2b45cf9c91f7f619e3fdb163f2ef` |
| Core 安装清单 | `425d792e504df359472c61a292bbd8461a203b14d069f3d651adf9c18bb31a07` |
| Receiver 安装清单 | `abadc496d103b0b6432399ba1dfd987d42fdb86f74cdd3cd4b1828799fe392b2` |
| 实际绑定修订 | `784` |
| 已读回配置摘要 | `8cd6912d35876fb2ed0345ecd3d4e2773986d19cff5520408e70bd604d731b43` |

最新 Tunnel 进程 PID 为 `21334`，health 为 HTTP 200；自有监督机制及原 Profile
保持运行。Profile 使用自有 integration entry，入口指向本次 schema 修订前缀。
正式远程源码 checkout 保持
`e900773fc39d61559a128e7438337ca39d12c02c`。

## Skills 与私有知识插件

三套 Skill 的自有副本已在 Windows、WSL 和 `1302-1` 部署并核对。

| Skill | 四文件摘要 |
|---|---|
| `acs-source-evidence` | `f4b9acd69bc9d48762e116ce027acd39dd7c1ba002dd9bcf84727b3a24d0cd68` |
| `acs-runtime-model` | `a716e6b252bf16cdb7ca54abb35c65266bfb04dd3eb967495d54a1978eca0106` |
| `acs-web-collaboration` | `39f0aff1a30127151ce2cd0be6f03b45eb3fdd4c9c9941a9bb326c45ec37b5b6` |

Web Skill 本轮更新 3 个文件，decisions reference 保留其内容；Source 与
Runtime 两套摘要保持上表身份。

现有[私有知识插件](https://chatgpt.com/plugins/plugins_6ab3e2ad1350819187cc2e88ee62ccdd)
当前版本为 **0.1.4**，release 为
`pluginrel_6acce0418fbc8191a5b62c6a705de78c`，账户范围为 USER/PRIVATE。
本次受保护更新的 overlay 包含 **5 个文件**：3 个 Web Skill 文档和
2 个 manifest，独立 Gate PASS；冻结 ZIP 的 SHA-256 为
`471e13a857c135389fc502897605c55867db6a66c407b4e7bdcbc5ce95ac8d25`。

最终远端读回确认本次 5 个文件精确匹配，并重新读取此前 8 个
Source/Runtime 文件确认字节一致，合计 **13 个不同文件**核验通过。
此前 0.1.3 release `pluginrel_6accd8e449848191b5721fdf8e12b91d` 的
10 文件更新与读回保留为该版本的历史结果。

## 源码候选与后续核验

| 源码状态 | 本修订冻结时读回 |
|---|---|
| 分支 | `codex/core-cleanup` |
| 原机器文件系统起点 HEAD | `689d47b6a6824198e1906ec5b587e08ef68ca9b5` |
| 原起点 tree | `9e033cf1cc9de0c3e1febb83ac821b01c1bf581a` |
| 已提交 schema 兼容性候选 | `3fe5c3e9d762c39ff3c249073606d24254b15546` |
| 已提交候选 tree | `80e3e159ff2fc672486c50a815176c699a4ddfca` |
| 当前工作树 | 显式 Source 分组元数据与相应记录已冻结，待提交 |
| 评审入口 | [现有 Draft PR #12](https://github.com/D1ChangGeng/Agent-collaboration/pull/12) |
| 本修订提交 / Push / CI | 待提交后绑定实际新 SHA 读回 |

先前 `fde54aed7a5be145a1ba5e34d9fcf453dad6d288` 候选的离线 schema
AttributeError 已由 `3fe5c3e9d762c39ff3c249073606d24254b15546` 的兼容性修订
及其验证覆盖。当前 CI 已验证 Runtime 与 PostgreSQL 范围，Source 分组
元数据修订通过本机 Gate 与 catalog contract；新提交的 CI 状态按实际运行读回。

用户 README、`docs/client/` 与 `.git-rewrite/` 工作保留。
源码候选、已安装 wheel、远程 checkout 和插件 release 分别保留自己的
身份与证据。正式 Runtime 发布沿独立 Release 流程进行。

客户端收尾步骤是对现有自定义连接执行 **Refresh**，再开启新对话加载工具定义。
提交、Push 与 CI 的后续读回绑定 PR 中的实际新 SHA。
