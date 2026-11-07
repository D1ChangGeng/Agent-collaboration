# 08｜版本适配、无损迁移与现有成果保护

## 不存在唯一“上一版当前状态”

本版在以下 ACS 状态均可直接使用：v1.0 全未实施、已实施部分 WP、已实装 P0、已实装 P0/P1、已有 P2，以及后续更高软件版本。所有逻辑基于真实 Git/运行时证据，不通过手动填写“当前处于 WPxx”决策。

## 旧消息、协议和数据库不变语义

不修改已存在的消息作者、消息 ID、原文、历史 reply_to 关系、request key、旧 Native receipt；旧 MCP 工具默认值/输入校验/权限语义不被新 HTTP 合同替换。客户端 SDK/API 新版本可新增字段，但旧 reader 必须按所支持的实际版本读取，不能将未知版本当空值。

## 改数据库前必须完成

检视实际 schema 与索引、现有 operations/Inbox/Outbox/Node Journal 和迁移状态。优先增量扩展而不是并行创建同义表；新字段需要是否 nullable、历史值 unknown、版本/权限/索引/预算定义。主动 schema adoption 只由授权 Operator 执行；正常启动不得静默迁移现网数据库。

## 双写与回滚

若迁移涉及旧新接口共存，先让 reader 能理解新增状态，再启用 writer；混合版本接收端必须 capability check。回滚不能删除未完成消息、operation、旧回复关系或尚未调和的原生副作用证据，不能通过数据库恢复触发重复 Native 输入。采用真实备份/恢复演练，保留失败记录。

## 已完成旧 P2 功能

已有草稿/附件/已读/搜索不删除；若它们具备真实数据则迁移和恢复必须保留，涉及修改时回归其安全和兼容。仅将它们从新里程碑的 gating criteria 中剥离，不能使已交付用户的行为退化。

## 修改范围与能力声明

新增 Harness Adapter 的 `supported` 声明必须绑定实际版本、OS、Host、auth、Adapter 版本和证据。对已经验证的 Codex/OpenCode 不扩大到未测版本。对不能执行原生协议测试的组合可实现 typed unsupported 并按资格标 `blocked/unverified`，不得推导生产可用。
