# 原消息与回复的有界正文和真实续读

接续 `eba6f1172dd6f90b7165f118774c1a8a2fc0e9ac`，分支 `codex/core-cleanup`。
完整目标仍在继续；没有生产迁移、远端切换、Push 或发布。

## 实际实现

`read_message(max_inline_bytes=31)` 曾返回 12,000 字节的内嵌回复，原消息
的预算没有作用于回复。现在原消息和首条回复分别按字节预算分页，保持
各自真实句柄、作者、正文及精确回复关系。每个正文都提供可回传的下一页
动作；`wait_for_response` 保留并合并这些动作，不暗发消息或改变满足条件。

极小预算放不下引用回复首个 UTF-8 字符时，当前响应只呈现引用和空片段，
`next_offset=0` 表示尚有内容，下一步显式读取动作给出足够空间。请求正文
的非法字节偏移仍拒绝；后续字符需要更大预算时，返回动作也能继续前进。
当前响应没有越过调用者的预算，没有静默丢弃正文。页间继续执行参与者、
项目和当前 Grant 校验，引用不是权限。

公开 catalog 9、read 输入版本 3、结果 revision 2 同步真实代码/描述/默认：
每个正文预算 1–65,536 字节，默认 16,384。Message packet、存储/签名字段、
原文和首条回复索引不变，不需要数据库迁移。目录生成保留既有结果类型
顺序，避免同一合同因 set 顺序变化而生成不同字节。

涉及 `runtime/communication.py`、`communication_tools.py`、公开 JSON 合同、
测试、CI、通信说明和随软件分发的恢复 Skill 参考。主要关联
R17/R19/R27/R32/R34，权限配对验证关联 R04/R33。

## 实际验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 原实现的内嵌预算、引用与双正文续读 | 3 项复现失败 | `before.xml` |
| 修改后的初步正文与等待检查 | 4 passed | `after.xml`、`wait.xml` |
| 字节边界、独立正文、默认预算、撤销/第三方权限 | 7 passed / 1 skipped | `boundaries.xml`；真实隔离 PG，模型另验 |
| 正文、自然消息、历史、重连、HTTP/撤销回归 | 89 passed / 2 skipped | `final-regression.xml`；新增后续字符边界由上项重验 |
| 最终源码的真实 Codex 读取者 | 1 passed，49.26 秒 | `model-23bc3bd2b0c349998d3915261898372b.xml`、`reader/` |
| 实际新 wheel 独立安装 | 106 文件匹配、46 表、2 消息/1 回复 | `installed-candidate.json`；脚本，无模型 |
| 私有 Linux 同字节副本 CI 默认组件范围 | 887 passed / 723 skipped，0 failed，207.22 秒 | `ci-components-linux-current.xml`；模型/DB条件分别验证 |

真实读取者 A 是独立 Windows Codex CLI 普通 engineer。B 是另外绑定身份的
脚本普通联系人，经同一正常 ACS send 主动回信，报告正文 26,097 字节。
A 的初始任务不含末尾验证标签；A 从自己 MCP 的等待结果出发，继续读取
回复句柄的 offset 16,384，并在最后输出准确标签。实际有一项完成的续读
调用；原始 JSONL 中 started/completed 是同一调用的两个事件。
没有 Native 调用、外部正文中继或数据库写入代发。这个使用证据是“一位
真实模型读取者 + 脚本对照 B”，不是双模型或 Native 验收。

源码清单核对 109 个文件；公开事件保留，推理事件不纳入呈现材料。较早的
45.40 秒读取者检查也保留。模型不是根据字符串出现自称成功：判据同时检查
真实 read_message 续读参数、预算、最终标签和无 Native 副作用。

软件版本沿用 `0.1.0`，不是开发包 v2.33。当前 wheel SHA256：
`29abf0f09f1923152cfb146bd5bbaa0fdbf088ab84a4056aa459eb18ec9ad1dd`。

## 尚未验证

本阶段没有重新资格化 OpenCode/所有 Harness 对长回复的模型理解，也没有
扩大 Native、Shared/Systemd 或生产吞吐量声明。旧协议事实和既有真实双模型
证据保留各自源码范围。完整 R01–R34 审查与支持矩阵仍需继续；部署切换和
发布保留其授权边界。
