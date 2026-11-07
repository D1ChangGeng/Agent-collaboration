# 实施决策与源代码吸收日志（填写模板）

每条记录包含 `id`, `change_item`, `actual_ACS_paths`, `actual_Orca_paths/revision`, `already_implemented?`, `gap`, `reuse_first_option`, `chosen_delta`, `why_minimal`, `security_impact`, `tests`, `evidence_refs`, `migration_needed`。

判断 Orca 模块时必须标清：源码确证/文档说明/测试实现/工程推断。Orca 的源码存在不证明 ACS 能直接借用该接口；Host 插件能力未公开时记录 `host_extension_required`。不得复制任务编排领域来补通信功能。
