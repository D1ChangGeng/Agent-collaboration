# ACS 机器文件系统能力产品契约

状态：**Accepted implementation contract**（已接受的实现契约）。日期：2026-10-12。
本文件定义已接受的产品行为、实现迁移和验收要求；实现状态以实际代码及验收证据为准。
现有实现依据：源码提交 `689d47b6a6824198e1906ec5b587e08ef68ca9b5`。

## 1. 默认行为

ACS 提供目标机器上的通用文件工具。用户在安装或会话中选择机器、操作系统账户和工作目录，Agent 随后通过 `read_file(path)` 等工具操作该环境的当前文件。

**owner 默认读取范围等于所选操作系统账户的实际读取权限：该账户可读的任何路径均可读取。** 绝对路径、相对路径、`~`、父目录、正常符号链接及 Windows 驱动器、UNC 路径按目标 OS 规则解析。隐藏、未跟踪、Git 忽略、非 Git、二进制和大文件均在此范围内。

`path` 与 `cwd` 定位文件。账户权限、容器及用户显式配置的安全 Profile 决定访问边界；隔离由对应账户或容器实施。shared 部署继续应用其既有身份、Grant、Policy 和隔离配置。

文件读取和修改遵循当前用户请求的意图及账户权限。当前机器与账户选择持续到显式切换或撤销。Core 自动维护连接、当前身份、内部修订、撤销检查、防重放和执行回执。

## 2. 原生工具参考

OpenAI 的 Codex prompting guide 展示了必填参数只有 `path` 的 `read_file` 示例，并建议以 shell 和 `apply_patch` 组成基础编码工具。[Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)

OpenCode 提供 read、write、edit、glob、grep 和 apply_patch；read 支持行范围读取，工具权限可独立配置。[OpenCode Tools](https://docs.opencode.ai/docs/tools/)

goose Developer 文档以用户权限解释可访问文件；原生 write、edit 从调用上下文取得工作目录，write 默认创建父目录。[Developer 文档](https://raw.githubusercontent.com/block/goose/main/documentation/docs/mcp/developer-mcp.md)、[原生实现](https://raw.githubusercontent.com/block/goose/main/crates/goose/src/agents/platform_extensions/developer/mod.rs)

据此，本契约采用常见文件动作与会话上下文。ACS owner 的默认账户访问范围是本契约的产品选择；参考产品的实际访问范围依其运行配置确定。

## 3. 公共 API

| 工具与必填参数 | 行为 | 可选参数与默认行为 |
|---|---|---|
| `read_file(path)` | 读取当前文件，返回文本或 Base64 字节 | `encoding="auto"`（可选 `utf-8`、`base64`）；文本 `start_line=1`、`end_line`；字节 `offset_bytes=0`、`length_bytes` |
| `list_directory(path=".")` | 列出文件、目录及链接 | 默认直接子项；`recursive=false` |
| `glob(pattern, path=".")` | 查找匹配路径 | `*`、`?`、`[]`、`**` 按搜索根下的相对路径匹配 |
| `grep(pattern, path=".")` | 搜索文本内容，返回路径、行号及片段 | 默认逐行正则；`fixed_strings=false`、`case_sensitive=true`；可选 `file_glob` |
| `write_file(path, content)` | 创建或覆盖文件 | `encoding="utf-8"`（可选 `base64`）；`create_parents=true` |
| `edit_file(path, old_text, new_text)` | 替换唯一精确匹配 | UTF-8 文本；零或多个匹配返回 `edit_conflict` |
| `apply_patch(patch)` | 按补丁内路径新增、修改、移动或删除文件 | 采用 `*** Begin Patch` 格式，路径使用同一机器和目录上下文 |

各工具统一接受可选 `machine_id`、`cwd`。读取、枚举和搜索接受 `max_output_bytes`、`cursor`；枚举与搜索另可提供 `limit`：

- 省略机器和目录时使用会话选择；续页时使用游标已记录的实际上下文。
- 行号从 **1** 开始，`end_line` 为包含在内的结束行；省略结束行表示读到文件末尾，按输出预算分批交付。字节偏移从 **0** 开始，`length_bytes` 是原文件字节数；省略长度表示读取剩余字节。显式行范围与字节范围互斥，字节范围使用 Base64 交付。
- `max_output_bytes` 为内容区编码后的字节预算，文本按 UTF-8、二进制按 Base64 输出计量；`limit` 为条目或匹配数量。两者为正整数，省略时采用当前传输与上下文的交付预算，结果报告实际预算。
- 输出和扫描采用分页、流式读取或分批交付。预算决定本次交付量，文件大小及搜索范围保持调用者选择；`next_cursor` 与 `complete` 表明继续位置和完成状态。

公开必填字段只表达文件动作。机器文件服务的就绪条件是已选机器、账户身份和文件连接。Project、Scope、WorkItem、AgentSlot、Grant、revision、digest、deadline 等信息由协作关联或内部记录承载。

结果包含实际 `machine_id`、`account`、绝对 `path`、`observed_at`，以及 `content`、`entries` 或写入回执。读取报告编码、原字节范围和可用行号；链接报告请求路径与解析目标；分页报告截断位置和续页信息。

```json
{"tool":"read_file","arguments":{"path":"../notes.txt"}}
{"tool":"read_file","arguments":{"machine_id":"build-linux","path":"~/logs/build.log"}}
{"tool":"edit_file","arguments":{"path":"config.txt","old_text":"mode=dev","new_text":"mode=prod"}}
```

## 4. 机器与会话上下文

安装保存默认机器及账户，新会话继承该选择。会话保存独立的 `(machine_id, account_binding, cwd)`；账户由可信连接绑定。工作目录采用安装或会话明确选择的目录，缺省为目标账户主目录。SourceBinding 可建议仓库目录与版本，用户或 Agent 选用后更新该会话上下文。

单次 `machine_id`、`cwd` 覆盖仅作用于该调用。另一机器使用本会话为其保存的目录或安装默认目录；相对 `cwd` 基于该机器的会话目录解析，`~` 指向其所选账户的主目录。接收请求时固定上下文，服务以请求局部目录执行操作。

两个会话可同时在不同机器读取同名相对路径。游标记录实际机器、账户、路径和查询；续页沿用原请求路径或返回的绝对路径，并固定在该目标。会话默认选择变化后，已正确寻址的续页仍继续读取原目标。显式参数与游标目标或查询冲突时返回 `argument_conflict`。

## 5. 文件语义与错误

读取使用 OS 文件 API 直接取得请求范围。`auto` 按实际字节返回 UTF-8 或 Base64，报告实际编码；二进制分页解码可恢复原字节。文本分页保留字符边界，超长单行以游标中的字节位置继续。续页检测到文件替换或修改时报告 `file_changed`，固定版本读取使用显式 Source 操作。

符号链接按目标 OS 规则解析；遍历记录已访问目录身份以处理链接环。隐藏项、被忽略文件及仓库外路径按实际权限访问。搜索流式扫描至完成，分页记录遍历和文件内位置；文本搜索报告二进制跳过项，二进制内容可通过 `read_file` 读取。

服务内部串行处理同一目标的编辑，写入前再读并检查精确匹配。普通文件按 OS 支持采用临时文件和替换，链接与硬链接保持本机文件操作语义。外部进程并发修改遵循 OS 语义，检测到变化时报告冲突。跨文件补丁逐文件记录实际结果，失败时列出已完成和待处理路径。

错误明确区分 `not_found`、来自 OS 的 `permission_denied`、`machine_offline`、`authentication_failed`、`revoked`、显式 Profile 的 `profile_denied`、`edit_conflict`、`file_changed`、`argument_conflict` 和参数或编码错误，并附实际目标及原因。写入重试按内部请求身份和回执去重；断连后的不确定写入先读回实际结果。

## 6. 服务结构与 Source 迁移

Core 独立公开机器文件服务，复用现有 Machine、Connection、Runtime 与账户绑定。一个可移植文件后端使用目标 OS API；Local、SSH、Node 适配器传递同一结构化请求与结果。SSH 调用固定文件服务程序，文件操作由目标账户的服务完成。

```mermaid
flowchart LR
    A[Agent 文件工具] --> B[Core：会话上下文与身份]
    B --> C[Local / SSH / Node 适配]
    C --> D[目标账户：可移植文件后端]
    D --> E[OS 文件 API]
    E --> A
```

文件服务独立处理请求，native Harness Session 的忙闲状态属于其执行链路。跨机器信任、撤销及防重放复用现有 ACS 机制；Domain 保持既有协作状态权威。

SourceBinding 提供仓库、位置和版本指导。Git 状态、commit、tree、快照和 CAS 用于显式复现与 Evidence 操作；Review 和验收固定实际候选及证据身份。日常文件操作读写当前 OS 内容。现有 owner 主 worktree、当前修改观测及显式 revision 读取保持其 Source 语义。[Owner Runtime](../../../../docs/runtime/OWNER-RUNTIME.md)、[Runtime adoption contract](../../../../docs/runtime/UPGRADE-CONTRACT.md)

| 实现基线 | 实现迁移 |
|---|---|
| `runtime/mcp_runtime.py` 及工具元数据 | 更新通用文件工具的描述、参数及分派，接入机器文件服务 |
| `runtime/project_service.py`、`project_source.py`、`source.py` | Source 读取以明确的 `read_source_file`、`list_source_files`、`search_source_files` 名称提供；复用现有快照、CAS、`read_source` 与 `read_diff` |
| `runtime/surface_config.py`、`surface_entry.py` 及现有机器连接适配 | 保存账户与会话选择，复用机器连接及认证，配置独立文件服务入口 |
| 新 `runtime/machine_filesystem.py` | 集中实现可移植 OS 文件动作、分页、搜索及编辑冲突处理 |

迁移更新实际调用方和工具元数据。既有项目身份、Root/Route、SourceBinding、工作项、连接及历史 Evidence 保留其记录；shared 按原有配置运行，机器工具依其明确配置启用。

## 7. 实现后验收

| 场景 | 通过标准 |
|---|---|
| 仓库外文件 | 在账户主目录的临时非 Git 目录创建合成 `.env`；绝对路径、`../`、`~` 与链接读取内容一致，报告实际目标 |
| 当前文件与权限 | 读取已修改、未跟踪、隐藏、被忽略及非 Git 文件；OS 拒绝的测试路径返回 `permission_denied`，显式 Profile 拒绝有独立原因 |
| Harness 忙时远程读取 | native Session 执行任务期间读取目标机器文件，服务及进程读回证实由独立文件服务完成 |
| 大文件、长行与二进制 | 按调用者范围及交付预算分页，拼接与原字节一致；二进制 Base64 解码一致，长行持续推进 |
| 搜索与链接 | 查到隐藏、被忽略及大文件中的匹配；链接环遍历终止；未完成扫描报告续页位置 |
| 两会话两机器 | 同名相对文件各归正确机器；单次覆盖保持调用局部语义；改变会话默认后正确寻址的旧游标继续原目标 |
| 修改、断连及撤销 | 精确编辑正确，零/多匹配冲突；服务并发编辑及重放回执正确；补丁失败报告实际结果；重连恢复连接，撤销阻止后续操作 |
| 项目与 Source 迁移 | 原项目、Root/Route、协作及证据身份一致；显式 Source 工具读取指定版本；现有 shared 隔离与工作流回归通过 |
