# Porpita 桌面客户端 · 全覆盖 UI SPEC

**设计已推进至第 90 轮。** 覆盖 20 个功能域、371 个条目。第 87–89 轮已归档，第 90 轮完成 F01（首次设置/导览/Landing）与 F02（Porpita 手机端/工件诚实不可用边界与翻译统一）的局部修复、单元测试与 Windows 隐藏窗口 Electron 实机核对。 [第 87 轮](ITERATION_87.md) · [第 88 轮](ITERATION_88.md) · [第 89 轮](ITERATION_89.md) · [第 90 轮](ITERATION_90.md)

| 查什么 | 入口 |
| --- | --- |
| 现有界面、子区、组件族和用例 | [UI Inventory](UI_INVENTORY.md)；[源码发现索引](source-index/README.md)；[共享组件使用位置](source-index/primitive-usage.csv) |
| 逐项现状、目标、源码、状态、证据和验收 | [Coverage Matrix](COVERAGE_MATRIX.md)；[可筛选 CSV](coverage-matrix.csv) |
| Session、Workspace、顶层 Tab、Tab Group、SidePanel | [对象与完整交互规范](WORKSPACE_INTERACTION_SPEC.md)；[各 SidePanel 能力与复用](SIDEPANEL_CAPABILITY_MATRIX.md)；[分组对照试验](GROUP_TRIAL.md) |
| 组件、布局、文字、状态与动效 | [共享视觉与交互规范](VISUAL_INTERACTION_SYSTEM.md) |
| 使用路径、结果、证据缺口 | [回放与验收](PLAYBACK_SCENARIOS.md)；[观察证据](evidence/README.md) |
| 来源、现版差异、覆盖边界 | [版本与证据身份](SOURCE_BASELINE.md)；[待闭环项](COVERAGE_CLOSURE.md) |
| 决策、Orca 复用与实施顺序 | [决策与分批](DECISIONS_AND_SEQUENCE.md) |

工作循环：用户在 Session Index 找到实际 Harness Session，在 Workspace 打开并和其他会话/工具并行工作，经顶层 Tab 切换与恢复上下文。原生 Chat、Terminal、文件、Diff、Browser 继续拥有各自的内容与操作；Project、Route、Identity、Harness 和 Machine 提供关联与筛选。设置、任务、自动化、插件和远程工具以它们现有的业务对象为中心。

矩阵锚点指向 Porpita 隔离工作树 `codex/porpita-ui-spec-90`。Windows x64 Candidate 11、开发构建、Linux 原生运行端与图形验收包各有源码身份。 [来源与身份](SOURCE_BASELINE.md)

第二至八轮建立窄窗、信任确认、已有 Chat 搜索、Vault 原位导航、配对历史搜索与 Explorer 恢复。第九至十一轮在开发预览中组合本地 Workspace、标题栏分组和固定范围 Explorer。第十二至十四轮推进实际进程恢复、从已开会话定位和拖放组织。统一 Session Index 的多来源状态、跨 Host、完整 Explorer 与发行平台按验收矩阵继续推进。 [第十二轮](ITERATION_12.md) · [第十三轮](ITERATION_13.md) · [第十四轮](ITERATION_14.md) · [证据](evidence/README.md) · [待闭环](COVERAGE_CLOSURE.md)

《参考包》的 Confirmed 和 D-001–D-009 提供已确定的产品方向；Recommended/Open 是待验证的输入。以本次请求的整客户端范围为准；参考包中的操作说明和文件名单只作为背景。研究范围包含所有桌面入口、条件路径及客户端可见原生窗口。移动端原生应用、独立 Web 客户端、第三方站点和第三方插件任意内部内容由各自项目负责；桌面里的配对、链接、插件承载、权限、回退与这些内容的交界仍在清单内。

**使用方法。** 按 Inventory ID 定位到矩阵。修改 `catalog/` 或证据映射后，在有 Porpita 依赖的环境用 `node tools/source-index.cjs <Porpita 工作树> source-index` 更新索引，再运行 `python tools/build_coverage.py --source <Porpita 工作树> --history D:/Chatgpt/Porpita`。原始候选归档由 `--history` 解析。结构检查验证来源、父子和回放引用，验收范围由对应记录说明。
