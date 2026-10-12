# 机器文件系统实现与验证记录

日期：2026-10-12。状态：实现、受影响路径回归、实际跨机器读回和安装核验已完成；
冻结候选的提交与 CI 读回由现有 Draft PR #12 跟踪。

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

产品契约见 [机器文件系统契约](MACHINE-FILESYSTEM.zh-CN.md) 和
[工具使用指南](../../../../docs/runtime/MACHINE-FILESYSTEM.md)。

## 回归与独立复核

| 验证范围 | 结果 | 适用版本 |
|---|---|---|
| Linux 七模块 PG/TLS/Source/Project/HTTP 组合 | 100 passed，119.48 秒 | 文件语义审计修复后的组合；服务进程 OS 锁由下一组覆盖 |
| Linux 最终 filesystem/PG/TLS 三模块 | 19 passed，6.21 秒 | 包含服务进程 OS 锁的冻结实现 |
| Windows 最终文件系统用例 | 13 passed，1 项权限场景按平台跳过，共 14 项 | 最终文件系统实现 |
| Setup unittest | exit code 0 | 本轮候选；执行记录未采集用例数量 |
| Skill validation | 通过 | 本轮知识包 |
| 独立代码复核 | 全部 9 项修复检查 PASS | 冻结实现 |

各运行按自己的模块与版本范围记录，数量按上述范围分别引用。
较早 Linux 93 项结果属于本轮前期选择；最终候选使用表中两组结果。
历史 P1/P2 Gate 保留其原始输入、绑定和结论。

## 实际 MCP 与 SSH 读回

最终 stdio MCP 公开 **48 个工具**，`read_file` 仅要求 `path`。
两次 MCP 会话的机器与目录上下文互相独立。

| 实际路径 | 账户与场景 | 结果 |
|---|---|---|
| Core 本机 WSL | `d26fo`；合成隐藏文件、仓库外目录、write/read | 通过 |
| Node `1302-1` | `changgeng`；合成隐藏文件读取及精确编辑 | 通过 |
| 游标与文件动作 | 二进制字节续页、改变默认机器后沿原目标继续、glob/grep/patch | 通过 |
| 固定 SSH 服务 | 固定服务 argv、JSON stdin、读取真实远程 README | 通过 |

二进制页解码拼接的 SHA-256 为：
`1333fecd12640fb14a1602358f3e1ac54f39104ceed8f73e44b2e51d36dd337b`。

最终本机 README 读取单次实测耗时
`0.03216319900820963` 秒；该数值描述本次读取。
前轮 stdio MCP 旅程同样通过 48 工具及上述文件场景，使用安装候选 wheel
`2dc78dc7e3e49841a056ce50304742f8dda335fbabed08f739c9785d1e993177`。
最终实际读回使用下节列出的冻结 wheel。

## 安装与运行身份

Core 与 Receiver 已安装同一最终 wheel，各端 **113 个安装文件**核验通过。
Wheel 中的 **101 个 Runtime Python/SQL 文件**与当前冻结源码逐字节一致。

| 资料 | SHA-256 或读回值 |
|---|---|
| 最终 wheel | `8dad97729d3527ad1c28c7ec0e5a6ed8e6faf2b265f4977f581fa3605c553da7` |
| Core 安装清单 | `6b7a57edaabdc73ce91f3b037a7bcee763359f3a5e25d45fc52fe200ceae189f` |
| Receiver 安装清单 | `27f3ac1ea321d6a6425709f4ead10f70f82f44321c15fb9dec0b37678efa1977` |
| 实际绑定修订 | `783` |
| 已读回配置摘要 | `94fd57ecad846ce79a19af66bfee41487cd0069cd4c7a8cacbf2af11601f86ad` |

验证时 Receiver 为 active/running，Tunnel 进程 PID 为 `14383`，
监督机制运行并沿用原 Profile。连接绑定读回为 health HTTP 200，Profile
使用自有 integration entry，该入口使用最终候选。原生配置、账户选择与
正式远程源码 checkout 保留原身份；远程 checkout HEAD 为
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

| 源码状态 | 冻结时读回 |
|---|---|
| 分支 | `codex/core-cleanup` |
| 本轮基线 HEAD | `689d47b6a6824198e1906ec5b587e08ef68ca9b5` |
| 基线 tree | `9e033cf1cc9de0c3e1febb83ac821b01c1bf581a` |
| 工作树 | 本轮代码与文档为尚待提交的冻结修改 |
| 评审入口 | [现有 Draft PR #12](https://github.com/D1ChangGeng/Agent-collaboration/pull/12) |
| 提交 / Push / CI | 评审冻结后进行，结果绑定实际新提交 |

用户 README、`docs/client/` 与 `.git-rewrite/` 工作保留。
上述源码候选、已安装 wheel、远程 checkout 和插件 release 分别保留自己的
身份与证据。正式 Runtime 发布沿独立 Release 流程进行。

客户端收尾步骤是对现有自定义连接执行 **Refresh**，再开启新对话加载工具定义。
提交、Push 与 CI 的后续读回绑定 PR 中的实际新 SHA。
