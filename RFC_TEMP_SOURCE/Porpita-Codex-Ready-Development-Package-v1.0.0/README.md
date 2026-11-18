# Porpita｜初代桌面客户端完整实现开发包

**执行入口：[START_HERE_CODEX.md](START_HERE_CODEX.md)**  
包版本：1.0.0 · 编制日期：2026-11-08 · 本包是开发规范，不是已构建的 Porpita 应用。

## 交付目标

以 Orca 的真实桌面产品为基线，原生保留其界面、交互、Native Chat、Harness Runtime、工作区和执行可视化；以 ACS Core 接管 Agent 间通信；完成独立品牌、安装、首次启动与真实客户端验收。用户打开的是 **Porpita**，不是 Orca 加一个管理面板。

执行顺序：**原生复用 → 产品整合 → 品牌独立化 → ACS 通信替换 → 完整客户端验收 → 有依据的专属能力渐进增强**。工程上允许互不依赖的工作并行；任何中间里程碑都不是最终交付。

## 已锁定的决定

| 事项 | 决定 |
|---|---|
| 产品主体 | Porpita，独立桌面应用；ACS Desktop 是技术定位，不是替代产品名 |
| 客户端路线 | 基于 Orca 的源码派生应用；插件可作为内部模块，**不是必须先交付的产品阶段** |
| UI 基准 | 原生复用，不先设计新导航、组织树、看板或新的 Chat 渲染器 |
| 通信权威 | ACS 管身份、消息、回复、历史和送达事实；原生执行仍由宿主/Harness 管理 |
| Task/Run/Gate | 作为可选工作流保留和适配，不进入 ACS Core，也不成为普通通信前置条件 |
| 研发重心 | 真实功能接通、正常使用、体验与交付；不再开展泛化防御建设 |
| 当前成果 | ACS P0/P1/P2 已有源码；直接复用，不重新执行旧包全部工作 |
| 版本处理 | 对当前工作树增量接续；参考 SHA 不是要求回退的指令 |
| 默认首发验收 | Windows x64（本包根据现有 Windows 使用环境选定的实施默认）；保持 macOS/Linux 构建与原生能力，不虚报其实机资格 |
| 完成对象 | 可安装应用、真实双 Agent 通信与原生 UI、原始体验证据；不是接口/截图/局部 Demo |

## 文件导航

- `docs/00_PRODUCT_AND_SCOPE.md`：完成定义、范围、首代能力。
- `docs/02_TARGET_ARCHITECTURE.md`、`docs/03_COMMUNICATION_REPLACEMENT.md`：内核替换范围与数据所有权。
- `docs/04_HOST_RECEIVER_AND_SESSION.md`：Python Core 与 TypeScript 宿主实际接线。
- `docs/05_ONBOARDING_CORE_LIFECYCLE.md`：无开发命令的安装、首次启动、托管 Core 与已有服务接入。
- `docs/06_IDENTITY_AND_CONTEXT.md`：内部组织映射与 Agent 首次上下文。
- `docs/07_NATIVE_UI_REUSE.md`：保留的 UI 与首代最小扩展。
- `docs/09_BRAND_AND_DISTRIBUTION.md`：品牌、兼容命名、上游服务、分发与许可边界。
- `docs/12_BUILD_INSTALL_RELEASE.md`、`docs/13_FUNCTIONAL_ACCEPTANCE.md`：构建、安装、真实产品验收。
- `tasks/`：可以连续执行的工作包；`contracts/`：对应的范围、路径、功能和验收清单。
- `handoff/`：执行记录模板，初始状态均为尚未检查，不代表实现失败。
- `references/`：带固定提交的源码索引与历史审计摘要，不是新的开放式研究任务。
- `tools/`：轻量包检查、工作树只读检查、最终交付记录检查。不是新增产品基础设施。

## 直接使用

将本包解压在开发工作区之外或文档目录中，把 `START_HERE_CODEX.md` 全文交给 Codex。让它访问现有 ACS 仓库和 Porpita/Orca 工作树即可；不需要解释上一轮执行进度。缺少 Porpita 工作树时，从锁定的 Orca 基线建立本地派生仓库，保留上游历史。

包自身检查：

```sh
python tools/validate_package.py
python -m unittest discover -s tests -v
tsc -p contracts/tsconfig.json
```

这些命令只检查开发包；绝不能据此声明 Porpita 已实现或已验收。
