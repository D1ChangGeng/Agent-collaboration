# 本开发包的使用约束

本目录是工程交接资料，不是 ACS 仓库根目录。不要用本文件覆盖目标仓库的 AGENTS.md。后续 Codex 从 START_HERE_CODEX.md 开始。

规范优先级：当前用户范围与边界 > docs/00 和 docs/03 的 MUST > 机器契约与其定义的 HTTP v1 > 其余实施建议。现有 MCP v12 的历史行为由旧接口契约约束，HTTP v1 不覆盖旧工具字段。发现冲突必须先修正包内一致性并记录，不能选择较弱保证。

所有附带 fixtures 为 synthetic_fixture。包自检不是目标系统验证。sources 标注 source_read 的内容可作为事实，implementation_check 是实现时待确认，不得混用。
