# v1.1 完整开发目标与资格分离

| 输入/边界 | 当前采用行为 | 当前证据 |
|---|---|---|
| 用户要求全部 P0/P1/P2 开发能力 | 25个改造项、40条需求、35个API、30项UI/来源合同逐项闭合，剩余开发项0 | ../acs-development-capabilities-20261107/development-capabilities.json |
| v1.1 默认 P2 可选 | 用户已明确启动，C22–C25与13个P2操作全部实装；canonical tier保留 | 同目录 FINAL_REPORT.md；最终76项真实API/服务组合 |
| 旧T006与修订MCP兼容 | 保持歧义时提交前拒绝、零广播及显式选择，不改旧MCP返回语义 | 原有Core用例及旧报告保留 |
| 安全原生queue/steer | 仅在独立证明能力后使用；其他busy延迟，unknown不当idle | Driver/Host合同与准入回归 |
| 冷恢复及同Message续接 | 原进程停止、原session/journal/profile与当前签名授权齐备才恢复，保留所有历史效应 | 恢复组件；ACK/唤醒31项；最终Core/TLS组合 |
| Native原始来源 | 本地journal或认证远端readback；Core ACL/注册及Node当前读取权限分别检查 | 来源28项；当前76项组合 |
| Orca接入 | ACS实际verifier/backend/router及原Host查询已实现；实际Host独立串行授权 | orca_receiver_backend.py；SDK210；当前Core/PG/TLS组合 |
| 历史Native资格 | 当前Driver/lifecycle源码变化，旧E3/E4不作为当前源资格；原记录保留 | 新qualification-matrix.json |
| Native委托/条件性Driver | transcript/控制/附件适配遵循Host合同，缺能力typed unavailable；新增Claude/Pi要求确切目标 | SDK集成合同；包的条件性要求 |
| 旧普通read行为 | 仅显式true转交native-source扩展，默认/false保持原调用形状 | 原兼容修复及当前MCP/HTTP回归 |
| 候选包与生产 | 当前2.3.1候选以wheel SHA及191文件SHA区分，仅临时安装 | 新package-facts.json |

开发包原件、失败日志、消息作者/原文/回复关系和生产数据未改。
验证按实际范围记录，不声称96个旧GWT原样全部完成或实际Orca已资格化。
旧限定范围裁决保留在新交付目录 prior-scoped-reports/SCOPE-DELTA-REPORT.md。
