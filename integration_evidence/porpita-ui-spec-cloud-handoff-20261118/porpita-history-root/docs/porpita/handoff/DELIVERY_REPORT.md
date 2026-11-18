# Porpita 0.1.0 交付与验收记录

Windows x64 11 安装候选已通过开发包 22 项必验场景，交付状态为 `PRODUCT_ACCEPTED`。试验使用同一份安装器和匹配的安装 ASAR。

| 项目 | 当前交付 |
| --- | --- |
| 安装器 | [Porpita-0.1.0-windows-x64-setup.exe](../../../dist/Porpita-0.1.0-windows-x64-setup.exe)，406,847,312 字节 |
| SHA-256 | `b7f817ffa12fbf42b05195a91948c64619fcab33d8c938b152184fcdb912a90b` |
| 安装 ASAR | `370b91f7f850fc16f0500e44e5e52395830d4d3b7d7f283b4b549d721507359e` |
| Authenticode | `NotSigned` |
| Orca 基线 | 1.4.214，`26179069b664b2fc172963564ed419d97892b6c9` |
| Porpita 源码 | 本地 `codex/porpita-desktop`，基线加[精确源码补丁](../evidence/20261109/porpita-source-candidate11.patch)重建 `2c1447f1e54c9deed41af5108a7f402d429e5c9a`。补丁已在独立 Git 索引验证。 |
| ACS 源码 | 隔离交付工作树提交 `c6bf795be35cc1db8a444ff07837a46009ae99e0` |
| 随包 Core | ACS 2.3.1，wheel SHA-256 `a4deca4bc03473d4972c72a53cf6e3dde07cc541b6bc28323b5c5c0b2e9f2ec4` |

原生工作台通过工作树、编辑、Diff、提交、终端分屏和浏览器试验。真实 Codex 与 OpenCode 用各自身份完成开发任务、自测、独立复核和显式回复。两个实际 Host 完成 Worker 提问、回复和单次结算，远端从本机物化位置读到与原件一致的附件。

长历史试验保留 65 条记录。该次安装版从提交回执到界面显示为 11.5 秒。搜索、旧页、私人未读、静音和归档在真实服务上核对。实际 Core 断开后接回原实例，卸载重装保持项目、配置和原 Native 来源。实测重连完成后，重开设置页显示了最新连接状态。

## 安装版验收

| 场景 | 实测结果 | 证据 |
| --- | --- | --- |
| UX01 安装并首次启动 | 通过 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-fresh-managed-setup.json](../evidence/20261109/installed11-fresh-managed-setup.json) |
| UX02 原生工作台完整 | 通过 | [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| UX03 原生Agent执行体验 | 通过 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| UX04 两个Agent自动接入 | 通过 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-native-identities.json](../evidence/20261109/installed11-native-identities.json) |
| UX05 真实跨Harness来回通信 | 通过 | [installed11-local-collaboration-proof.json](../evidence/20261109/installed11-local-collaboration-proof.json) · [installed11-local-native-readback.json](../evidence/20261109/installed11-local-native-readback.json) |
| UX06 无任务通信与最小协作入口 | 通过 | [installed11-no-task-conversation.json](../evidence/20261109/installed11-no-task-conversation.json) · [installed11-collaboration.png](../evidence/20261109/installed11-collaboration.png) |
| UX07 忙时消息和原生队列 | 通过 | [installed11-agent-question-approval.json](../evidence/20261109/installed11-agent-question-approval.json) · [installed11-agent-question-core.json](../evidence/20261109/installed11-agent-question-core.json) |
| UX08 提问与人类审批 | 通过 | [installed11-agent-question-approval.json](../evidence/20261109/installed11-agent-question-approval.json) · [installed11-native-approval.png](../evidence/20261109/installed11-native-approval.png) |
| UX09 消息历史/实时/搜索 | 通过 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-collaboration.png](../evidence/20261109/installed11-collaboration.png) |
| UX10 消息跳到实际执行 | 通过 | [installed11-native-target-source.json](../evidence/20261109/installed11-native-target-source.json) · [installed11-retained-core.json](../evidence/20261109/installed11-retained-core.json) |
| UX11 私人阅读与草稿 | 通过 | [installed11-history-and-read-state.json](../evidence/20261109/installed11-history-and-read-state.json) · [installed11-reopen-after-reinstall.json](../evidence/20261109/installed11-reopen-after-reinstall.json) |
| UX12 文件与图片分享 | 通过 | [installed11-attachments.json](../evidence/20261109/installed11-attachments.json) · [installed11-group-and-attachment-core.json](../evidence/20261109/installed11-group-and-attachment-core.json) |
| UX13 可选任务编排仍可用 | 通过 | [installed11-paired-worker-completion.json](../evidence/20261109/installed11-paired-worker-completion.json) · [installed11-paired-worker-exchange.json](../evidence/20261109/installed11-paired-worker-exchange.json) |
| UX14 Gate与群组语义保留 | 通过 | [installed11-group-gate.json](../evidence/20261109/installed11-group-gate.json) |
| UX15 退出重开与短暂断开 | 通过 | [installed11-service-reconnect.json](../evidence/20261109/installed11-service-reconnect.json) · [installed11-reopen-after-reinstall.json](../evidence/20261109/installed11-reopen-after-reinstall.json) |
| UX16 目标更换与重复提交 | 通过 | [installed11-native-target-source.json](../evidence/20261109/installed11-native-target-source.json) |
| UX17 已有Core服务登录 | 通过 | [installed11-existing-service.json](../evidence/20261109/installed11-existing-service.json) |
| UX18 品牌和服务出口 | 通过 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-brand-scan.json](../evidence/20261109/installed11-brand-scan.json) |
| UX19 原生UI与响应体验 | 通过 | [installed11-stock-ui-comparison.json](../evidence/20261109/installed11-stock-ui-comparison.json) · [installed11-native-workbench.json](../evidence/20261109/installed11-native-workbench.json) |
| UX20 同一候选升级/卸载交付 | 通过 | [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) · [installed11-uninstall-reinstall.json](../evidence/20261109/installed11-uninstall-reinstall.json) |
| UX21 实际远端Host链路 | 通过 | [installed11-second-host-ready.json](../evidence/20261109/installed11-second-host-ready.json) · [installed11-remote-file-verification.json](../evidence/20261109/installed11-remote-file-verification.json) |
| UX22 最终功能与路径收口 | 通过 | [candidate11-source.json](../evidence/20261109/candidate11-source.json) · [installer-prototype11.json](../evidence/20261109/installer-prototype11.json) |

## 使用与范围

[使用说明](LOCAL_RUNBOOK.md) · [交付清单](../../../delivery-manifest.json) · [14 条通信路径](MESSAGE_PATHS.md) · [28 项功能](FEATURE_COVERAGE.md) · [品牌和服务](BRAND_AND_SERVICES.md)

Windows x64 是实测桌面范围。两个 Host 在同一台 Windows 机器上使用独立进程和配置。已有服务登录使用真实的私有环回 ACS。macOS、Linux 平台构建配置和 9 个 Node 远端模板目标已保留并构建校验，桌面安装、其它 Harness 组合以及物理多机链路待实测。旧 federation 全量测试含原终端和消息正文中转的预期，覆盖范围以聚焦回归和上述真实安装试验为准。
