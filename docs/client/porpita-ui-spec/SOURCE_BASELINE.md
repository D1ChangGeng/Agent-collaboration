# 来源与证据身份

| 对象 | 身份与边界 |
| --- | --- |
| 参考包 | `RFC_TEMP_SOURCE/Porpita-Workspace-UI-Spec-Reference-v1.0.0/`。D-001–D-009 与 Confirmed 提供产品定位与对象边界。Recommended/Open 的使用见 [决策](DECISIONS_AND_SEQUENCE.md)。文件内操作说明仅作资料；本次范围来自用户请求。 |
| 当前 Porpita | 本机 `D:/Chatgpt/Porpita`，`codex/porpita-desktop`，HEAD `517555d5ce68ba8e417cdd2192b561a4061237ef`，tree `f587fac1669e4b0fba14faabcece5098a220336a`。只读 Git status 无跟踪修改；已有未跟踪构建产物。 |
| Orca 基线 | `26179069b664b2fc172963564ed419d97892b6c9` 已核对为祖先。官方现版资料作为同类体验对照不替换此版本。 |
| 安装版 | Windows x64 Porpita 0.1.0 候选 11。已安装 `app.asar` hash `370b91f7f850fc16f0500e44e5e52395830d4d3b7d7f283b4b549d721507359e` 与交付记录一致。记录绑定 tree `2c1447f1e54c9deed41af5108a7f402d429e5c9a`；不是当前 HEAD 的字节同构安装。 |
| HEAD 运行产物 | 同一 Porpita 工作树运行 `electron-vite build --outDir <隔离目录> --mode e2e`。为隔离输出提供现有 `NODE_PATH` 后构建完成；前次失败是外部路径没解析到本地 `@orca/process-host`。使用标准开发 Electron 和已有依赖/资源，未打包或安装。main/index.js SHA-256 `a68d664c7c06c5ca05e06f81b816c068d478db34b6ec8b82e53004d10b845f0e`；renderer/index.html `5897cfaba890872a5136f61556b5df533b2be12cec3464d9b73e96392293cf3c`。 |
| 工作目录 | Agent-collaboration `main`，HEAD `e5d71968a13e67e3dc51e318867d4ed9a1f946ac`，有原有修改和未跟踪文件。本次新增 `docs/client/porpita-ui-spec/`；未改其余内容。 |

源码侧比较：安装 tree 与 HEAD 在 `assets`、`tab-bar`、`tab-group`、`right-sidebar`、`sidebar`、`editor`、`ui`、`browser-pane` 的路径上无 Git diff；它们仍可能受外部依赖/运行条件影响。对比发现协作组件、onboarding controller、Mobile Hero、帮助文字、Native Chat 定位路径与 Core/runtime 等有差异。回放分别绑定安装版或 HEAD 构建。HEAD 构建已补测首用、深色、Dock/活动/看板及协作未配置、通用、手机入口；连接后的协作、原生来源定位等继续待验。历史证据保留原身份。

Git 和本机运行界面足以检查当前用户要求的基线；未连接远端工程 checkout。Windows renderer 保持后台隐藏，未建立真实远程设备、未提交外部消息。源码索引属静态发现；浏览器/原生集成状态由各自回放判定。

## 第二轮来源

本轮产品代码位于 `codex/porpita-delivery-closeout` 的隔离工作树，行为修复提交 `8040ab3a81ea577e7bde4b2d5190978c6d87c57d`，文案清理后 HEAD 为 `ac16c8eb3d901a5bd0b74d852afc4c634cb3eca1`，树 `3b70a60808e598d0e96297237232a173da667a90`。文档提交 `5e7ee4accd7a64965823573162479f9520da8ad4` 已推送并复核私有 GitHub 默认分支。覆盖矩阵链接本地隔离树，历史证据从原 Porpita 归档读取。

| 证据 | 本轮身份 |
| --- | --- |
| I201–I207、I214–I218 | Windows x64，`electron-vite build --mode e2e`，后台隐藏且独立档案，CSS DPR 1。构建 `out/main/index.js` SHA-256 `48ee8a1fec13be0ea52884735d0932b669927b47583460314823f227c4db2144`，`out/renderer/index.html` `026b9a0d73bbb687dff8dd0630c5131e1805a8927a177adee211c2183a81b74e`。 [回放](evidence/iteration-02-windows/run.json) |
| I208–I210 | 已安装的 Windows x64 Candidate 11，同机启动、断开和重连真实托管 Core，独立档案。 [回放](evidence/iteration-02-core/run.json) |
| I211–I213 | 同树的 Orca 组件夹具，Chrome 157.0.8103.50，真实键鼠输入和浅深色。样例数据；主题、宽度、动作与结果记录在 [Shape 记录](evidence/group-shape/interaction.json)。 |

Candidate 11 的完整客户端源码树可从 GitHub 基线和归档的补丁重建。ACS wheel 本轮离线复建得到原 SHA-256。原安装器资格和新开发构建的局部结果分别记录。 [私有仓库交付记录](https://github.com/D1ChangGeng/Porpita/blob/5e7ee4accd7a64965823573162479f9520da8ad4/docs/porpita/DELIVERY.md)。

## 第三轮来源

第二轮的提交对象 `ac16c8eb3d901a5bd0b74d852afc4c634cb3eca1` 仍可读取。原关联工作目录已不存在。第三轮复建了独立工作树 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03`，分支 `codex/porpita-ui-spec-03`，本地提交 `272c1e95894fe2a6df6edc7f9848bc013662b44c`，树 `41c13c6dbbe61ddcf33685e01c047f7180f62058`。矩阵源码链接指向该树。

| 证据 | 主体 |
| --- | --- |
| I301 | 以 ac16c8eb3d 构建的 Windows 基线，使用同一测试场景。直接执行 main 文件时 Electron 报告运行时版本 43.8.6。 |
| I302–I308 | 第三轮 Windows 开发构建，Electron 43.8.6，1280×800 和 600×400 CSS px，DPR 1。英语浅色与简中深色均回放。main/index.js SHA-256 `48ee8a1fec13be0ea52884735d0932b669927b47583460314823f227c4db2144`，renderer/index.html `90540fc4cdb9d60aa4d94d9761dc5882d34242ea9a200b8f05a8c27ff78ae6c6`。 |

两套真实桌面回放都使用一次性配置和两个本地 Git 项目。Codex 为 Candidate 11 自带的 Windows 二进制，SHA-256 `9d563ee4e0441ff9d59d612013e0460ddf8e5709735c2d9f6b98b7ef8ca4eb42`。未登录、未发送草稿、未请求模型。GitHub 产品文档与安装验收仍按各自版本记录。 [第三轮证据](evidence/README.md#第三轮)

## 第四轮来源

基线为第三轮提交 `272c1e95894fe2a6df6edc7f9848bc013662b44c`。在同一隔离目录 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 建立 `codex/porpita-ui-spec-04`。本地提交 `1bf354a12a353c4ceb5a0fcf183f2449037add48`，树 `14411367d447a85e9d46ce69c4d76b319aed479b`。源码工作树干净，提交未推送。UI SPEC 与回放保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/`，目录尚未纳入该仓库版本跟踪。

- I401 为第三轮 Windows 开发构建的基线回放。I402–I411 为第四轮 Porpita 0.1.0 开发构建，使用锁定的 Electron 43.8.6 和 Candidate 11 内置 Codex 0.166.0。每次运行创建独立档案与 Git 项目，使用后台隐藏窗口。第二轮安装资格继续按原交付记录。 [第四轮证据](evidence/README.md#第四轮)
- 第四轮 `out/main/index.js` SHA-256 `48ee8a1fec13be0ea52884735d0932b669927b47583460314823f227c4db2144`。 `out/renderer/index.html` SHA-256 `bea0bab706c6854039503ba48f452a98b0319aaf2dadd888b7c91e2c3689eafa`。 `out/renderer/assets/App-DniwztzI.js` SHA-256 `11fe2188bde9a6fe40a672ebc7b661a2cc9078e8dc3222a939e5890d16818af9`。

## 第五轮来源

基线 `1bf354a12a353c4ceb5a0fcf183f2449037add48`，在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 创建 `codex/porpita-ui-spec-05`。本地提交 `f3a1dacb16776f84a573a979cb4c2421c8c3abef`，树 `eaf3f346d997e2f6ddc60371136cbafd9f8fc88a`。工作树干净，提交未推送。UI SPEC 和回放保存在 Agent-collaboration 工作区的既有目录，尚未纳入该仓库版本跟踪。

- I501 以第四轮开发构建为对照。I502–I510 来自第五轮 Porpita 0.1.0 开发构建，锁定 Electron 43.8.6 与 Candidate 11 内置 Codex 0.166.0，两个独立档案在同一 Windows 主机上使用真实回环配对。 [回放](evidence/README.md#第五轮)
- 第五轮 `out/main/index.js` SHA-256 `bb46b8a8a19fb43d57d2f7151e1985f65d900ea5ef77d8712aa054259f07096b`。 `out/renderer/index.html` SHA-256 `25e1ea4547a5022230998e20448513cd887824f097ed9343009eff526753529e`。 `out/renderer/assets/App-_FEoUCz_.js` SHA-256 `44f58de9a7206fb8bae5f8b03f8b7f98852e427271961b067277630c68c592bc`。

## 第六至八轮来源

基线 `f3a1dacb16776f84a573a979cb4c2421c8c3abef`。三个增量共用隔离目录 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03`，分支 `codex/porpita-ui-spec-06`，本地提交 `85c63f04cc5ef2473ce60deb23672947462a1874`，tree `8200583c4f879cb1878d7fc815c80b7a90b61f88`。Porpita 隔离源码工作树干净，提交未推送。Agent-collaboration 的 `docs/client/porpita-ui-spec/` 持有 SPEC、工具和回放，尚未纳入该仓库版本跟踪。

- I601 来自第五轮开发构建。I801 来自第八轮修改以前的开发试验。I602–I605、I701–I704 和 I802–I805 来自包含三个增量的最终开发构建。Porpita 0.1.0 运行在 Windows x64 Electron 43.8.6；一次性档案、真实本地文件与合成历史记录用于后台 renderer 回放。发行包验收沿用原 Candidate 11 记录。 [第六至八轮回放](evidence/README.md#第六至八轮)
- 最终构建 `out/main/index.js` SHA-256 `bb46b8a8a19fb43d57d2f7151e1985f65d900ea5ef77d8712aa054259f07096b`、`out/renderer/index.html` `c2095ef5790ba244a73e59851ac8e505164cd997654512828943b3a962306f15`、`out/renderer/assets/App-B9awYiDA.js` `5861e262d2adc67bcf8786aa8c34a595eaceb5ec914d6088f5fe85af014feca6`。
- 仓库标准检查通过。Web 类型检查覆盖 15,488 个文件，变更质量门禁通过，焦点范围 13 个测试文件共 83 项通过。6 次 Windows 开发构建回放共 28 个步骤通过，另外 2 次对照共 3 个步骤。

产品交付参考继续由 Porpita 仓库维护，涵盖主 README 与多语言文档、安装器与 ACS 构建材料及平台资格。Windows x64 Candidate 11 是独立的 22 场景已验收产物。Windows ARM64、macOS 和 Linux 的桌面产物资格继续按平台表登记。本轮回放同时标出侧栏移动配对入口的中英文命名差异，纳入 M.01 的后续检查。 [Porpita README](<D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03/README.md>) · [产品身份](<D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03/docs/porpita/BRAND.md>) · [交付记录](<D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03/docs/porpita/DELIVERY.md>) · [平台资格](<D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03/docs/porpita/PLATFORMS.md>)

## 第九至十一轮来源

用户于 2026-11-15（日本时间）确认第六至八轮并要求继续相邻迭代。本轮在同一个 Porpita 隔离工作树上从 `85c63f04cc5ef2473ce60deb23672947462a1874` 创建 `codex/porpita-ui-spec-09`。预览提交 `068e2ce0be95d7eca46e3c3529d9fc17c186d718`，最终提交 `05156dbec9b29e0865f331f5f5c4b919c90177ec`，tree `42097edc5de547df76807b738eeae72a04def74f`。工作树干净，提交未推送。Agent-collaboration 本地 `docs/client/porpita-ui-spec/` 保存规范、目录、工具和证据，尚未纳入该仓库 Git 跟踪。

- I901–I1104 使用 Porpita 0.1.0 Windows x64 Electron 43.8.6 的隔离开发构建。英语浅色与简中深色各完成 11 个回放步骤。调用 Candidate 11 已归档的 Codex 0.166.0 二进制，使用真正的本地会话和文件，草稿未发送，用户档案和系统焦点保持隔离。 [英语](evidence/iteration-09-11-windows/run.json) · [简中](evidence/iteration-09-11-windows-zh/run.json)
- `out/main/index.js` SHA-256 `bb46b8a8a19fb43d57d2f7151e1985f65d900ea5ef77d8712aa054259f07096b`。`out/renderer/index.html` 为 `e78376985d4ce25459a4a83c56dbc1e6c96a091942f129188e0367b8095a1687`。`out/renderer/assets/WorkspacePreview-kLoNKmmK.js` 为 `e177552025f5a17cc66b967ebc2432d20c5142cfdf8bb13bdebfc1a3da710968`。
- Web 类型检查覆盖 15,494 个文件，变更质量门禁和常规提交检查通过。7 个相关测试文件共 12 项通过。
- 默认开关另建隔离构建并启动验证。正常工作台入口可见，预览标题、入口和加载引用均不在默认路径。复跑原 Worktree 双终端分屏、方向键、Esc 和 15%/85% 限位，四步通过。 [默认构建回放](evidence/iteration-09-11-default/run.json) · [第七轮行为复验](evidence/iteration-09-11-worktree-regression/run.json)

开发预览可由工作台侧栏进入。使用隔离 Porpita 工作树、已有依赖、开发 Electron 及已验收的本地 Codex 资源。PowerShell 中在该工作树执行：

```powershell
$env:ORCA_BACKGROUND_LAUNCH = '1'
$env:VITE_PORPITA_WORKSPACE_PREVIEW = 'true'
$env:VITE_EXPOSE_STORE = 'true'
node .\node_modules\electron-vite\bin\electron-vite.js build --outDir out --mode e2e
$env:PORPITA_SPEC_SOURCE = (Get-Location).Path
$env:PORPITA_SPEC_ENTRY = $env:PORPITA_SPEC_SOURCE
$env:PORPITA_SPEC_EXE = (node -e "console.log(require('electron'))")
$env:PORPITA_SPEC_LOCALE = 'zh'
$env:PATH = (Join-Path (Get-Location) 'resources/porpita-runtime/windows-x64/harnesses/codex') + ';' + $env:PATH
node D:/Chatgpt/Agent-collaboration/docs/client/porpita-ui-spec/tools/observe-installed.cjs .tmp/spec-03/workspace-preview-replay --workspace-preview
```

可用范围由显式开发构建控制。布局先存隔离 renderer 记录，验证到 renderer 重载。登录后真实输入、设备配对后跨 Host、多 Pane 组合、完整 Explorer 和发行平台仍按集成任务验收。 [实施顺序](DECISIONS_AND_SEQUENCE.md)

## 第十二至十四轮来源

用户于 2026-11-15（日本时间）确认第九至十一轮。本轮在 Porpita 既有隔离工作树从 `05156dbec9b29e0865f331f5f5c4b919c90177ec` 创建 `codex/porpita-ui-spec-12`。本地提交 `f99294721a447531184cfb13cb4b0aa3d95d1a55`，tree `ff1919de57c2fbede9602192fa34667f6604cbbd`。隔离工作树干净，提交未推送。规范、清单、工具与证据保存在 Agent-collaboration 的本地 `docs/client/porpita-ui-spec/`，目录尚未纳入该仓库 Git 跟踪。

- I1201–I1402 来自该提交的 Windows x64 开发构建。测试以真实本机 Native Chat、两个隔离 Git 工作树及实际 Markdown 文件完成。Codex 未登录，草稿未发送。完整退出后启动新 Electron 进程，核对当前使用同一一次性用户档案并保持后台窗口隔离。 [英语](evidence/iteration-12-14-windows/run.json) · [简中](evidence/iteration-12-14-windows-zh/run.json)
- `out/main/index.js` SHA-256 `fed8f55345c3b936f8f05eb8d2e8faea6f65306ee2624c8685c411548814d4c1`，`out/renderer/index.html` `feda60b07214c3cec2b2e0580a0c39129696a048a3ff9ece4cb239d2eae5ba0d`，`out/renderer/assets/WorkspacePreview-BcHHYQuH.js` `5f831c9bd4695dfe2446f4eb8185b8a32096d34a415a28f9e129a9d1fd3d4900`。
- 默认构建另验证普通工作台可进入，首次历史索引完成后五步搜索行为回归通过。 [默认入口](evidence/iteration-12-14-default/run.json) · [Vault 回归](evidence/iteration-12-14-index-regression/run.json)
- 该提交的 Web 类型检查、变更质量门禁及常规 Git hook 通过。主进程类型检查通过。最终聚焦套件覆盖已有搜索、输入焦点、文件浏览与标签拖放，10 个测试文件的 103 项测试通过。

沿用上文开发 Electron 构建和隔离路径，将测试入口改为 `node D:/Chatgpt/Agent-collaboration/docs/client/porpita-ui-spec/tools/observe-installed.cjs <输出目录> --workspace-continuity`。设 `PORPITA_SPEC_LOCALE=en` 或 `zh` 保留对应代码和主题。预览入口在侧栏「工作空间（预览）」。运行时布局由桌面主进程保存到当前档案的 `porpita-workspaces.json`，旧预览记录仅在首次没有档案文件时导入。批准后的原生执行、多物理 Host、系统辅助技术及正式发行验收保留各自运行条件。 [实现与条件](WORKSPACE_INTERACTION_SPEC.md)

## 第十五至十七轮来源

用户于 2026-11-15（日本时间）确认第十二至十四轮。Porpita 隔离工作树从 `f99294721a447531184cfb13cb4b0aa3d95d1a55` 创建 `codex/porpita-ui-spec-15`，最终本地提交 `7cd92fc853898c4097346e253e560241482a1707`，tree `70909bb853eaf366e84897949637411a311dfe97`。源码工作树干净，提交未推送。规范、清单和回放位于 Agent-collaboration 的 `docs/client/porpita-ui-spec/`，为该仓库的本地未跟踪材料。

| 构建 | 文件 | SHA-256 |
| --- | --- | --- |
| 开发预览 | `out/main/index.js` | `fed8f55345c3b936f8f05eb8d2e8faea6f65306ee2624c8685c411548814d4c1` |
| 开发预览 | `out/renderer/index.html` | `11da4fda7c185f5c61b3e3ec63f88a43b8e3c7c78d93daefd9074e1fe5480526` |
| 开发预览 | `SidebarSessionIndex-DSUCMZzy.js` | `69c2cd20c4016a8240745f6363e455526f958c92ebe5c7f5fe249e289ee49d2c` |
| 开发预览 | `WorkspacePreview-C6rYG2pJ.js` | `2f87c5a1ae41b4b228a65105e905ad914b4b102b13fa6f3b737698116c8ede79` |
| 默认构建 | `.tmp/spec-03/out-15-default/main/index.js` | `4b60a3820b2038e11a68f850c1815cddd349e341692b0b13ad501b91237e834b` |
| 默认构建 | `.tmp/spec-03/out-15-default/renderer/index.html` | `584b1a3ad8ebf43da8e2ecd544e8cc9cb53ab3e0feb8edce6f4061cecce1524e` |

- I1501–I1703 来自 Windows x64 的 Porpita 0.1.0 开发构建，Electron 43.8.6。英语浅色与简中深色各 13 步，记录 1280×800、1100×680、640×520 和 600×400 CSS px、DPR 1。采用独立档案、两个本地 Git 项目和合成 Codex 历史。运行未登录 Harness，草稿未发送。 [证据](evidence/README.md#第十五至十七轮)
- 默认构建各跑入口及原 Vault 历史操作，分别通过 1 与 11 步。两组构建均使用开发 Electron 与既有 Candidate 11 Codex 资源。安装版的资格继续沿用原交付记录。 [默认入口](evidence/iteration-15-17-default/run.json) · [Vault](evidence/iteration-15-17-vault-regression/run.json)
- Web 类型检查、变更质量门与仓库 Git hook 通过。搜索与焦点、原生 Session、Vault 选择等 10 个聚焦测试文件共 101 项通过。Inventory、矩阵和源码索引重新生成并校验。 [覆盖核对](coverage-audit.json)

使用上文相同开发构建及环境设置，把回放模式改为 `--sidebar-session-index`。通过 `PORPITA_SPEC_LOCALE=en` 或 `zh` 选择主题和语言。默认构建取消 `VITE_PORPITA_WORKSPACE_PREVIEW` 后各使用 `--workspace-preview-disabled`、`--session-history`。跨物理 Host、未开会话和统一状态、多平台与真实运行权限继续由相应场景验收。 [待闭环](COVERAGE_CLOSURE.md)

## 第十八至二十轮来源

用户于 2026-11-15（日本时间）确认第十五至十七轮。从 `7cd92fc853898c4097346e253e560241482a1707` 创建 Porpita 隔离分支 `codex/porpita-ui-spec-18`，本地提交 `1bb9c2cf6f8b496fce59952f82cc7eb7cbd2b0a6`，tree `5c921ddc019096ff4f2d38dd12ee967fb228feaa`。源码工作树干净，提交未推送。规范及回放保存在 Agent-collaboration 本地的 `docs/client/porpita-ui-spec/`，当前为该仓库的未跟踪资料。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `fed8f55345c3b936f8f05eb8d2e8faea6f65306ee2624c8685c411548814d4c1` |
| `out/renderer/index.html` | `c176d67c7fe341c891cc0045f57647401577b810a5c046612c8b0d99a154a374` |
| `SidebarSessionIndex-7gt-HqKE.js` | `70c1121f94cbf74768252a2e1e8658b901cc3f720dab60cfc5b1d29ed47153b3` |
| `AiVaultPanel-BJhnfLVK.js` | `fc522a82fb9fa48457fa90f2ad6d2d46c7940c86d0648c0626d3dce71a8c1645` |

默认构建输出在 `.tmp/spec-03/out-18-20-default/`。其中 `main/index.js` SHA-256 为 `4b60a3820b2038e11a68f850c1815cddd349e341692b0b13ad501b91237e834b`，`renderer/index.html` 为 `6347fea35b057bcbc5224c2a7fa4c76ff91564d2c91f5debc0afefc2416245b3`。

回放在 Windows x64 以开发 Electron 43.8.6 隐藏窗口执行。第十八轮使用本机实际扫描与合成 Codex 历史。第十九轮从 `out/main/index.js` 直接启动以使用现有的本地脚本 Codex app-server，驱动原生运行和审批事件。第十九轮 run manifest 上的 43.8.6 来自直接启动的 Electron。第二十轮使用同机两个独立档案和回环配对，实际查阅和恢复两来源的原生会话。 [运行与原始证据](evidence/README.md#第十八至二十轮)

最终源码的桌面回放共 70 步，包含 58 步中英文预览与 12 步默认构建回归。Web 类型、变更质量门及正常 Git hook 通过，12 个聚焦测试文件共 109 项通过。 [覆盖核对](coverage-audit.json)

预览设置及启动环境沿用第九至十一轮。回放选项为 `--sidebar-unopened-history`、`--sidebar-run-state`、`--sidebar-host-directory`。设 `PORPITA_SPEC_LOCALE=en` 或 `zh` 选择主题与语言。运行状态回放将 `PORPITA_SPEC_ENTRY` 指到 `out/main/index.js`，另外两组通过源码工作树启动。桌面安装资格继续按 Candidate 11 的交付材料记录。 [复现脚本](tools/observe-installed.cjs)

## 第 21–23 轮来源

用户于 2026-11-15（日本时间）确认第 18–20 轮。从 `1bb9c2cf6f8b496fce59952f82cc7eb7cbd2b0a6` 创建本地隔离分支 `codex/porpita-ui-spec-21`。提交 `e24cba9537024bf8359c2c3aa05f89cbd0550751`，tree `d41ee0638e779fd79d2d820472bd08ac49c433d2`，通过正常提交检查，源码工作树干净。规范与回放位于 Agent-collaboration 的本地 `docs/client/porpita-ui-spec/`。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `86c8f68c0dac60395acac03f382cb3625cc278b7dcdfa168c7082573583a3ebb` |
| `out/renderer/index.html` | `a312b5ed5bab0438f5a5a67d7637d0ebca097b7a398204fcdab9141a30005e53` |
| `WorkspacePreview-BMZwYR9e.js` | `af23569466d4b41f4156b77d310d1f1050d4f738a446edd14885f62b79de1cd4` |
| `NativeChatView-waaea9Iw.js` | `3c5e7158fb442b6099f23ba1fbec450183a1f6c5e1c7cec9acb72854340b3286` |

开发预览使用 Windows x64 的后台 Electron，取一次性桌面档案。跨 Host 回放经 `--workspace-host-continuity` 启动同一 Windows 上的两个隔离 Runtime，在回环认证传输中使用合成历史、已打开的原生会话与未发送草稿。`--workspace-continuity` 核对原工作空间、v1 实际档案与 v2 保存。代码构建、回放目录和设备边界见证据索引。 [复现脚本](tools/observe-installed.cjs) · [证据索引](evidence/README.md)

当前提交的 6 个聚焦测试文件共 22 项通过，覆盖布局存储、窗格归属、断线、草稿、命令面板和历史入口。桌面回放归档共 49 步：英语跨 Host 13 步、简中跨 Host 13 步、本机档案回归 23 步。生成的覆盖矩阵为 20 个域、305 项。 [覆盖核对](coverage-audit.json)

## 第 24–26 轮来源

用户于 2026-11-15（日本时间）确认第 21–23 轮。以 `e24cba9537024bf8359c2c3aa05f89cbd0550751` 创建本地分支 `codex/porpita-ui-spec-24`。源码提交 `27d76486e5fbe7937492dcd78a124d4570b2e935`，tree `f0119cc9e0351ed31b8ac86623ddb90bb3bdb278`。通过正常 Git 提交检查。源码工作树干净，提交保存在本地。规范和回放保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/`。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/renderer/index.html` | `2c28c3411c596a9ef004e27196e14f74f3efaa54c2e387e42e5075f73bf31a77` |
| `WorkspacePreview-CD6pkIpL.js` | `4107c079a750d9b40a98e68f4103001e01a18e66511a8af6887a3c7d3bf0879c` |

按现有 e2e 构建流程启用 `VITE_PORPITA_WORKSPACE_PREVIEW` 和 `VITE_EXPOSE_STORE`，构建通过 preload 与启动图检查。桌面回放从 `out/main/index.js` 启动，使用 `--workspace-explorer-continuity` 与 `PORPITA_SPEC_LOCALE=en`、`zh`。两个 Runtime 使用同一台 Windows 的不同一次性档案及回环配对。文件、历史和草稿均为测试数据，文件打开走实际的目录、RPC 和编辑器。4 个聚焦测试文件的 19 项验证覆盖布局迁移、会话来源、原 Explorer 范围和 Vault 回归。 [回放工具](tools/observe-workspace-explorer-continuity.cjs)

最终预览归档 57 步。中英文跨 Host 各 17 步，本机旧档案与已接受的工作空间行为 23 步。矩阵核对为 20 个域、308 条，新源码锚点均有归属。 [回放索引](evidence/README.md) · [覆盖核对](coverage-audit.json)

## 第 27–29 轮来源

用户确认第 24–26 轮。以 `27d76486e5fbe7937492dcd78a124d4570b2e935` 创建本地分支 `codex/porpita-ui-spec-27`。本轮源码提交 `918eb416ffdbfcc093e1b4fe6b10d096be399eb9`，tree `570fc2ad1e744d0f4f4db5c90912ad441813ba39`。源码通过正常提交检查。规范和回放保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/`。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/renderer/index.html` | `0e5554dcdbeb8205d6f26fad2535f54f46fa71407783013c05c7b577efbea1c0` |
| `StatusBar-CCL7wtGE.js` | `4105e10fb3cfb13a84c38a951def106c1f925ac71fa3203ff3e4fd9e15653482` |

以同一开发构建和 `--workspace-usage-continuity` 回放一台 Windows 上的两个隔离 Runtime。使用 `PORPITA_SPEC_LOCALE=en` 或 `zh` 选择对应主题和语言。账户读取走实际 Runtime，会话、文件和草稿由隔离档案提供。带百分比的截图用 37% 本机用量夹具检验原用量菜单及窄窗呈现。 [复现入口](tools/observe-installed.cjs) · [用量断言](tools/observe-workspace-usage-continuity.cjs)

Web 类型检查覆盖 15,518 个文件，4 项聚焦测试通过。最终预览归档 42 步，覆盖矩阵为 20 个域、311 项。 [回放索引](evidence/README.md) · [覆盖核对](coverage-audit.json)

## 第 30–32 轮来源

用户确认第 27–29 轮。以 `918eb416ffdbfcc093e1b4fe6b10d096be399eb9` 创建本地分支 `codex/porpita-ui-spec-30`。源码提交 `2cf198ae07b13662f675fc18fb5cd340e6a4eae9`，tree `f6af1b085dcc211c7d8de987c10b19f5d28515bc`。正常提交检查通过。规范和证据保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/`。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/renderer/index.html` | `6549b573c309e9783910e677833025174a49da9b704122d9e8a490fbb705604f` |
| `PortsStatusSegment-CoOufFbp.js` | `c9d73f34b08f5f59119380d9bc39e59a797f065c8f4cba3979875381f109f62c` |
| `ResourceUsageStatusSegment-RaRjFnXg.js` | `bbd42e79efc6554000ea3295e0eabfcc3658721361890a6f6c72df1ca27bab16` |

开发构建通过 preload 检查和渲染器启动图验证。Windows 隐藏窗口最终回放使用 `--workspace-ports-focused`，从两个实际工作树打开固定 Explorer。两个隔离 Runtime 在同一台机器上。扫描读取实际监听项，脚本只创建和关闭测试工作树内的环回服务。资源视图保留原生可见性门槛，资源汇总数字截图使用样本。首轮混合 Chat 证据来自早期 `--workspace-ports-continuity` 构建。 [回放工具](tools/observe-workspace-ports-continuity.cjs)

Web 类型检查覆盖 15,521 个文件。最终中英文各 7 步，另保留混合 Chat 首轮连续帧。覆盖矩阵为 20 个域、314 项。 [回放索引](evidence/README.md) · [覆盖核对](coverage-audit.json)

## 第 33–35 轮来源

用户确认第 30–32 轮。以 `2cf198ae07b13662f675fc18fb5cd340e6a4eae9` 创建本地分支 `codex/porpita-ui-spec-33`。源码提交 `055f1940179627aa0cffd8901828e11f7ea9f140`，tree `62e2cf9d21ba0fd743f10a91cdc42b2a548870cc`。正常提交检查通过。规范和证据保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/`。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/renderer/index.html` | `33290420a98a0ac3956d654979b80f349aec226563acadb098b136848e6945e0` |
| `PortsStatusSegment-CNuNAOdC.js` | `5057fd13d9a1e35d8b98a8499c076e083da48cddd8ce5a9727780e3f22816e46` |
| `ResourceUsageStatusSegment-Cnh_naQ7.js` | `050b73db47932009a2ea777eccba8b7eabdf5fd2df785f5a20d89f8b26693ef6` |

开发构建通过 preload 检查和渲染器启动图验证。最终回放使用 `--workspace-ports-focused --port-resource-management`，简中追加 `--compact-port-inspection`。Browser 从本机测试进程读取实际 HTML。资源树使用指向真实本机工作树的样本与渲染器可见性夹具，原生窗口保持隐藏，定位使用实际应用操作。 [回放脚本](tools/observe-workspace-ports-continuity.cjs)

Web 类型检查覆盖 15,522 个文件。最终中英文各 10 步，覆盖矩阵为 20 个域、317 项。 [回放索引](evidence/README.md) · [覆盖核对](coverage-audit.json)

## 第 36–38 轮来源

用户确认第 33–35 轮。隔离工作树从 `055f1940179627aa0cffd8901828e11f7ea9f140` 建立本地分支 `codex/porpita-ui-spec-36`。源码提交 `a5bf75fb6670dc08f27d2184297f1cf8e491829f`，tree `2bbd60e5ff6d5f875ebc86d2ac68ad07f6bbbbd6`。Porpita 源码工作树干净，提交留在本地。规范、脚本和证据保存在 Agent-collaboration 的 `docs/client/porpita-ui-spec/` 工作区文件。

| Windows 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/renderer/index.html` | `5c1f04e5b6ded7f5c309b9dea703e22622fe274225a6cd72e8f5f4523f44d25e` |
| `PortsStatusSegment-Oh2apV5D.js` | `29c5f54e734310ed09977560f7752d38ed56b2bd7041c990b8453e1ad3fd991b` |
| `ResourceUsageStatusSegment-D0od1RND.js` | `ed55696c26f42abcad5980a91bd2f0631e7fca1a1adef8e0027a688413c1b5b9` |

正常提交检查、preload 和渲染器启动图通过。Web 类型检查覆盖 15,523 个文件，两个聚焦测试文件共 5 项通过。回放使用 Electron 43.8.6 的隔离开发预览，开启 `--workspace-ports-focused --port-target-continuity`，简中增加 `--compact-port-inspection`。两个一次性配对档案运行在同一台 Windows 机器。端口及 Browser 页面来自实际环回服务。资源归属使用样本与渲染器可见性夹具，工作树和标签切换使用实际应用操作。 [回放索引](evidence/README.md#第-3638-轮) · [回放工具](tools/observe-workspace-ports-continuity.cjs)

英语和简中各完成 11 步与 8 段连续帧。覆盖矩阵包含 20 个域、320 项。 [覆盖核对](coverage-audit.json)

## 第 39–41 轮来源

用户确认第 36–38 轮。隔离工作树在 `a5bf75fb6670dc08f27d2184297f1cf8e491829f` 上建立本地分支 `codex/porpita-ui-spec-39`。当前源码提交为 `13c12691e07afbee42bbadf0595aac39afc326ca`，tree 为 `80fc1b44422af23f44b407529ee1c23aefdff49f`。Porpita 源码工作树干净，提交保存在本地。规范、回放工具及证据保存在 Agent-collaboration 工作区。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/preload/index.js` | `db20d420289efdf3a0b1e0fcc9f1b293c6a77541f5f821b78e36707ab6f00993` |
| `out/renderer/index.html` | `332e56af3fde9b922fbca0cc6e52aea13079896381f1b7754feb786044231af0` |
| `ResourceUsageStatusSegment-B8TK1_14.js` | `87dfc01aaee048c1d4bf8406b92d6d566df42567a8b0ea772bf738859a0675f2` |
| `WorkspaceSpacePage-HCY5-DWm.js` | `6aa64aedc2a6854932fbb5d7da7a014a3ab008c1846e15fb96d887756ec261d8` |

标准提交检查、Windows 开发构建和 Web 类型检查通过。Web 检查覆盖 15,523 个文件。最后两次渲染器修正使用仓库按目标构建配置，保有已验证的 main 和 preload 输出。回放入口使用 `--workspace-ports-focused --resource-terminal-continuity`，简中增加 `--compact-port-inspection`。实际工作树、PTY 进程和 Space 使用一次性 Windows 档案。回放沿用仓库诊断可见性夹具读取真实 PTY provider，保持原生窗口隐藏。诊断失败和 Space 开窗失败由测试注入，恢复路径交还真实调用。 [回放工具](tools/observe-resource-terminal-continuity.cjs)

英语和简中各完成 5 步、3 段连续帧和 1 张实际 Space 子窗口画面。四个聚焦测试文件共 15 项通过。覆盖矩阵包含 20 个域、323 项。 [回放索引](evidence/README.md#第-3941-轮) · [覆盖核对](coverage-audit.json)

使用同一构建另走 `--workspace-ports-focused --port-refresh-regression`，5 步通过。替换本机实际监听，从原工作树端口列表重新选择，确认 Browser 加载新环回页面。 [端口复验](evidence/iteration-39-41-port-regression/run.json)

## 第 42–44 轮来源

用户确认第 39–41 轮。隔离工作树从 `13c12691e07afbee42bbadf0595aac39afc326ca` 建立本地分支 `codex/porpita-ui-spec-42`。源码提交为 `85a2e8ad908b65dfa23bc870472dc4d9e3781f1a`，tree 为 `a0b383f7da38296243c924ab8fa685cf962d0461`。源码工作树干净。规范、回放工具与证据位于 Agent-collaboration 工作区。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/preload/index.js` | `db20d420289efdf3a0b1e0fcc9f1b293c6a77541f5f821b78e36707ab6f00993` |
| `out/renderer/index.html` | `a201663cf0af66d03734a2de723091f378586d55b3708283465853184ca1f23a` |
| `ResourceUsageStatusSegment-CG2YSEkz.js` | `7da9998fa02cf46b7e7164525ffdb39fed8c90f3aa8f062a758d1ffd11a91362` |
| `WorkspaceSpacePage-f2olmKnS.js` | `e65396a59d7c556502819dc519b7ee8f33bf5e542b648ab207f641dd9a75d506` |

预览由目标构建配置重新构建 renderer，沿用已核对的 main 和 preload。原有提交检查通过。回放使用 `--workspace-ports-focused --resource-terminal-continuity --resource-selection-continuity`，简中增加 `--compact-port-inspection`。英语和简中各完成 8 步，包含第 39–41 轮的相关路径复验。独立 Space 窗口和 PTY 所在窗口保持隐藏。PTY 使用诊断可见性夹具与真实进程，Space 使用真实扫描及 Porpita 在配置的临时目录创建的两个托管工作树。审阅在取消处结束。 [PTY 和开窗回放工具](tools/observe-resource-terminal-continuity.cjs) · [Space 导航和审阅工具](tools/observe-space-selection.cjs) · [回放索引](evidence/README.md#第-4244-轮)

Web 类型检查覆盖 15,523 个文件，两个聚焦测试文件共 12 项通过。覆盖矩阵包含 20 个功能域、326 项。 [覆盖核对](coverage-audit.json)

## 第 45–47 轮来源

用户确认第 42–44 轮。隔离工作树从 `85a2e8ad908b65dfa23bc870472dc4d9e3781f1a` 建立本地分支 `codex/porpita-ui-spec-45`。源码提交为 `550921aee05331a9921e615d5958a171b62cbd02`，tree 为 `6646040dbe6fcff48b95bf3f1c2571fe269c8dd0`。源码工作树干净。规范、回放工具与证据位于 Agent-collaboration 工作区。

| 开发预览文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/preload/index.js` | `db20d420289efdf3a0b1e0fcc9f1b293c6a77541f5f821b78e36707ab6f00993` |
| `out/renderer/index.html` | `dd8d85d434bac6c065d7a434b633e38d182e8b56b5f063d03fca5b910ade9e13` |
| `DeleteWorktreeDialog-BPf7cfiQ.js` | `6b287153a8398bde1e75b8fc02f74ebfa4bbdd79928b9e58b678d96bf8686786` |
| `space-D1JXbOGl.js` | `e2210accd32f75f16bd078269f49495f71de72f29a9fda04b6be28a32e770b8b` |
| `WorkspaceSpacePage-DLd6l36f.js` | `83829ccf9b6e5bc10fd8bd013cc8b4c9f03ff810b7366fa333e1f01ec9055f2c` |

预览按目标构建重新生成 renderer。英语和简中各通过 11 个步骤，包含已批准的资源和筛选审阅路径。运行使用 `--workspace-ports-focused --resource-terminal-continuity --resource-selection-continuity --space-cleanup-continuity`，简中增加 `--compact-port-inspection`。真实删除目标在应用创建的隔离临时目录内逐项核对。普通删除的部分结果由 Git 拒绝临时改动和另一个实际工作树的删除共同产生。再次接收主窗口发布验证保留的失败原因，重试经新的清理审阅。 [清理回放工具](tools/observe-space-cleanup.cjs) · [回放索引](evidence/README.md#第-4547-轮)

提交检查、renderer 构建和 Web 类型检查通过。Web 类型检查覆盖 15,524 个文件，三个聚焦测试文件共 5 项通过。覆盖矩阵包含 20 个功能域、329 项。 [覆盖核对](coverage-audit.json)

英语 Space 实况使用 CDP 帧。简中复验在对话框绘制后取 CDP 视口截图，两份回放使用同一个源码构建。

## 第 48–50 轮来源

用户确认第 45–47 轮。Porpita 隔离工作树从 `550921aee05331a9921e615d5958a171b62cbd02` 建立本地分支 `codex/porpita-ui-spec-48`。最终源码提交为 `8b2608c2ba5a963e0099fe8d7d95a6e065b29a44`，tree 为 `583c0b3b96ec3ccc2917f69dc3929fc2b7057edd`。规范、证据和回放工具位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `ff6a47037d98a2a396e23973ad854c783a21cdc8c0a2cd202260b7c8883449a7` |
| `out/preload/index.js` | `db20d420289efdf3a0b1e0fcc9f1b293c6a77541f5f821b78e36707ab6f00993` |
| `out/renderer/space.html` | `2ffa70dbff282b7a621892d7d2499473dc3e2798b0a8ceea9f987c6dd48e1b67` |
| `DeleteWorktreeDialog-BFTdOQPn.js` | `0f4a28a22b09e12ae65e665225a7060a57122a5f4eef1c0b482fcf7638b89cc1` |
| `PreservedBranchBatchReviewModal-BrV1g1di.js` | `90159937911b36464c8ccb6f4a336501f2a9dee994127c5a58cc351a4ded4645` |
| `space-ByBlubLt.js` | `a938beefef109b9753e3c0c9d4a560d3514e3e4313f25c8ebd4efad46abfb696` |
| `WorkspaceSpacePage-B9pKTirO.js` | `1b09b28d5b9be7f21f08000b7dad75377557de3f1698e69bb2ef4cf1eca0ed8c` |

按目标构建配置重建 renderer，沿用表中 main 和 preload。通过 `observe-installed.cjs --space-branch-review` 打开真实独立 Space。两次回放各使用新的临时档案和 Git 仓库，系统和用户 Git 配置在测试进程内隔离。CDP 截图对应隐藏窗口的实际内容视口。 [回放工具](tools/observe-space-branch-review.cjs) · [回放索引](evidence/README.md#第-4850-轮)

Web 类型检查覆盖 15,525 个文件。四个聚焦测试文件的 8 项通过，覆盖删除流程、窗口状态和分支复核。覆盖矩阵包含 20 个功能域、332 项。 [覆盖核对](coverage-audit.json)

使用独立 Git 配置运行底层真实 Git 套件，20 项中 18 项通过。异常登记夹具的工作树枚举和 Node 文件池响应断言失败。切回第 47 轮基线，在同一 Windows 与 Git 2.55.0 环境中单独运行这两项，复现相同失败。

## 第 51–53 轮来源

用户确认第 48–50 轮。Porpita 隔离工作树从 `8b2608c2ba5a963e0099fe8d7d95a6e065b29a44` 建立本地分支 `codex/porpita-ui-spec-51`。最终源码提交为 `0238ca1008813dec3c08ecf6ac1e4efe54d25d00`，tree 为 `39f6ce0ddfd5d7ad4d80e65c0b66ccb57695b2c1`。规范及回放工具和证据位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `d3f088889eba8ce267a4e3227ca2b39bc5e1fb52d469781b0f9dd785c87558b8` |
| `out/preload/index.js` | `db20d420289efdf3a0b1e0fcc9f1b293c6a77541f5f821b78e36707ab6f00993` |
| `out/renderer/space.html` | `cdc666a8c1ba40e792a70cea62803ca2d113b2d5027fbc5d32c8b9b0a6ac6ed9` |
| `PreservedBranchBatchReviewModal-CKpG80g4.js` | `ca25aa248d1c93cda45dcdbcdc2b9e3db53e70f94b35fd4f4e241ff518358b2d` |
| `space-Cz4mOtGJ.js` | `01da5100c58727407988faa5036b2c830e5cb5bd186766d78798cae759b81ae9` |
| `WorkspaceSpacePage-ylSYOcg0.js` | `db169179cfb4d43be22b3213ffbfd3e6bc85a82c9f6b7a51f95cc40187b0a9c0` |

使用范围构建配置重建 main 和 renderer，沿用表中 preload。用 `observe-installed.cjs --space-branch-review --space-branch-recovery` 运行英文和简中回放。均使用隐藏的 Windows Space、隔离 Git 配置及 Git 2.55.0.windows.5。基线回放使用第 50 轮构建和 `--space-branch-recovery-baseline`，新旧均实际推进同一测试用例中的分支并创建额外检出。 [回放工具](tools/observe-space-branch-recovery.cjs) · [回放索引](evidence/README.md#第-5153-轮)

提交检查通过。Node 和 Web 类型检查分别覆盖 18,351 和 15,525 个文件。5 个聚焦测试文件共 14 项通过，包含实际读数判定与同一提交上的锁冲突单元测试。覆盖矩阵包含 20 个功能域、335 项。 [覆盖核对](coverage-audit.json)

同一最终构建额外复跑第 48–50 轮原三步流程。Windows 英语回放确认清理失败、保留分支、取消与显式单项删除。 [三步回归](evidence/iteration-51-53-space-en/regression-48-50-run.json) · [断言](evidence/iteration-51-53-space-en/regression-48-50-checks.json)

## 第 54–56 轮来源

用户确认第 51–53 轮。Porpita 隔离工作树从 `0238ca1008813dec3c08ecf6ac1e4efe54d25d00` 建立本地分支 `codex/porpita-ui-spec-54`。源码提交为 `bfced033bf4d9620de9a7200c4064052e11c171b`，tree 为 `30748f72f62c39a3d469d32af13edd441ad44460`。规范、证据及回放工具位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `2bf888762e9608dd94ea074151179b972955d328d9fb8abac737c472bc353568` |
| `out/preload/index.js` | `ca66b6045066db43cd6b5dd982aea14d5781d9a7db79686fb4d6d6de24fadd36` |
| `out/renderer/space.html` | `659865f1f83277d2eff4398f534c8c636173f6ac3f7cfb59e7dab2e09b269c07` |
| `PreservedBranchBatchReviewModal-YzxDi9zD.js` | `2455fba29d3e50d563efd0dacd2f25816671eff3d9d1a88a9e01ecad4d169596` |
| `space-DjqcJ7yv.js` | `8cfedb75b4ba1c34f07179d6b7db457322a4a2b35144d8227cdeee3a4d7889b1` |
| `WorkspaceSpacePage-CZKg_N5J.js` | `c512ec4cb47e41692cfec9882cf223ccbb0aa4635c09d6a03d34803e014e7fcd` |

重建 main、preload 和 renderer。Windows 以 Git 2.55.0.windows.5 和一次性仓库回放 `observe-installed.cjs --space-branch-review --space-branch-checkout`。用实读路径和活跃工作树识别主窗口，另经真实 IPC 检查过期实例拒绝。释放检出由回放在相应的临时工作树中执行，提交在可见复核控件中完成。 [回放工具](tools/observe-space-branch-checkout.cjs) · [回放索引](evidence/README.md#第-5456-轮)

提交检查通过。Node 和 Web 类型检查分别覆盖 18,352 和 15,527 个文件。5 个聚焦测试文件的 14 项通过。覆盖矩阵包含 20 个功能域、338 项。 [覆盖核对](coverage-audit.json)

## 第 57–59 轮来源

用户确认第 54–56 轮。Porpita 隔离工作树从 `bfced033bf4d9620de9a7200c4064052e11c171b` 建立本地分支 `codex/porpita-ui-spec-57`。源码提交为 `07289c7936c50002294be227c9dd744578998608`，tree 为 `a2becf524a94bc2d74127c93a26eed7123a911cd`。规范、证据及回放工具位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `6640835aaef7b936ee1c4a8881eb720bdaf28e5a60a0a880d82930886e99ae16` |
| `out/preload/index.js` | `c9d3edbaa796f5c3995321eafa4976a12789ba9b968efad0470ba4ff014f3e0a` |
| `out/renderer/index.html` | `fa913164d3004fc015d4568f37eda202cc84d14081e4bbcc9157c078b348b75d` |
| `out/renderer/space.html` | `1b3ce93641d218a10493afeb3dcc05677b1aca57f45a1b3a9ad750597f64ab26` |
| `PreservedBranchBatchReviewModal-72eKYDD9.js` | `226e273e7e70f53b846ae23e55cfd3e5a2e8f6c54aa5d465c2860acdbc02f344` |
| `space-CNpJFMzU.js` | `d863aa56a564c7727faae77e3daf261b19c5de91ffc8ce5970896016ffe7aabd` |
| `StatusBar-BO3bLziX.js` | `809b2dd5ed6201a3507efea11a592b008e832a36fb360320a95a8c1827daadd4` |

重建 main、preload 和 renderer。Windows 以 Git 2.55.0.windows.5 和一次性仓库运行 `observe-installed.cjs --space-branch-review --space-checkout-return`。双语回放均从实际登记工作树打开开始，用可见状态栏按钮核对往返。另用 `--space-branch-checkout` 复跑第 54–56 轮，验证提交使返回入口撤下，再比对实际 Git 引用。 [本轮工具](tools/observe-space-checkout-return.cjs) · [回放索引](evidence/README.md#第-5759-轮) · [清理回归](evidence/iteration-57-59-space-en/regression-54-56-run.json)

提交检查通过。Node 和 Web 类型检查分别覆盖 18,352 和 15,528 个文件。5 个聚焦测试文件的 14 项通过。覆盖矩阵包含 20 个功能域、341 项。 [覆盖核对](coverage-audit.json)

## 第 60–62 轮来源

用户确认第 57–59 轮。Porpita 隔离工作树从 `07289c7936c50002294be227c9dd744578998608` 建立本地分支 `codex/porpita-ui-spec-60`。源码提交为 `c9704b50c342534fd16d5467789352ff0c6e7bdc`，tree 为 `00a3b787d9930623832f47d48cc1aa9b2a0167ca`。规范、证据及回放工具位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `6640835aaef7b936ee1c4a8881eb720bdaf28e5a60a0a880d82930886e99ae16` |
| `out/preload/index.js` | `c9d3edbaa796f5c3995321eafa4976a12789ba9b968efad0470ba4ff014f3e0a` |
| `out/renderer/index.html` | `13b739830b9cabe7f66ec32ffae5d105f8316c87ea40567b2c03c7575169b736` |
| `out/renderer/space.html` | `72bae9f5029caa5304efc6ebb770a63d84288532efb86a1b450d6c1d721e203a` |
| `PreservedBranchBatchReviewModal-DE-lm4Dv.js` | `1a18007ae58fe11109f6825f314f3d3c8112d17b055011ec9a0163ffbca7fc2f` |
| `space-IsJjFMmw.js` | `ca5a0b8cc752f2f8891f007dcdb568f47745d260bb35291c1ef95ffa85c7648e` |

重建 renderer 并核对复用的 main、preload 构建文件。Windows 以 Git 2.55.0.windows.5 和一次性仓库运行 `observe-installed.cjs --space-branch-review --space-checkout-drift`。基线额外传入 `--space-checkout-drift-baseline`。双语回放实际移动 Git 工作树、刷新应用目录、返回原复核并重新提交。英语另核对原路径由不同实例复用，以及第 57–59 轮正常返程。 [本轮工具](tools/observe-space-checkout-drift.cjs) · [回放索引](evidence/README.md#第-6062-轮)

提交检查和覆盖 15,528 个文件的 Web 类型检查通过。3 个聚焦测试文件的 7 项通过。覆盖矩阵包含 20 个功能域、344 项。 [覆盖核对](coverage-audit.json)

## 第 63–65 轮来源

用户确认第 60–62 轮。本组从 `c9704b50c342534fd16d5467789352ff0c6e7bdc` 接续，在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-63` 提交源码。HEAD 为 `a2864fbb77e1a7972b000b7272e0af3762ab0650`，tree 为 `44f114df549541c92b08966a5032b05fd8af68f7`。规范、证据及回放工具位于 Agent-collaboration 工作区。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `572587da455f4299ba630c5d6d1b0c41a9506573641d3df101f159c648f37db5` |
| `out/preload/index.js` | `fbb9c34a7e26404f61a54e8157ad4ac41698df3bf298411cf47580f3212abdb3` |
| `out/renderer/index.html` | `2880f3fae51f9645815bb75e1f23147072d11406a3c2ca58618f4f959640566b` |
| `out/renderer/space.html` | `1a95ee7ff4cd4b5bd71f9f2eec38ac1eedea74cd202ab20540ec0b40533443b3` |
| `out/renderer/assets/PreservedBranchBatchReviewModal-Bf_2txwF.js` | `5ff1e9bbf2c3c11bf5d50542c1dbf308d1c3411d581775c67e1cb1478f76b453` |
| `out/renderer/assets/space-B7wXgUdQ.js` | `33bd33f9edef5d5789f31f3e4ce2f53e292338e1ccae1cd2696118e5131b115b` |

以 `e2e` 模式构建 Main、Preload 和 Renderer。Windows x64 使用 Electron 43.8.6、Git 2.55.0.windows.5 和独立一次性仓库。隐藏窗口回放参数为 `--space-branch-review --space-checkout-drift --space-checkout-inspection`。英语、简中各八步，另用英语复跑第 60–62 轮七步。 [本轮工具](tools/observe-space-checkout-inspection.cjs) · [回放证据](evidence/README.md#第-6365-轮)

提交检查通过。Web 类型检查覆盖 15,528 个文件，Node 类型检查覆盖 18,353 个文件，四组现有聚焦测试共 13 项通过。覆盖矩阵包含 20 个功能域、347 项。 [覆盖核对](coverage-audit.json)

## 第 66–68 轮来源

用户确认第 63–65 轮。本组从 `a2864fbb77e1a7972b000b7272e0af3762ab0650` 接续，Porpita 隔离工作树位于 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03`。本地分支为 `codex/porpita-ui-spec-66`，当前 HEAD 为 `5e7ed685d13c20e0258a861901f621b81dcfde46`，tree 为 `570caddfde53ed2704cd44500b29043f3c5c2df1`。规范、回放工具和证据在 Agent-collaboration 工作区。

英简中、WSL 与 Windows 本机全组回放的源码提交为 `568bed56c3a7203d5d7410c942bc423658bcc467`，tree 为 `3ad75ebae298efe9c714511034a426acac5eadb0`。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `4a60c4c910b8ce4be35bb0c4b055abf93556a0401594bbc7de6808bb92e32f60` |
| `out/preload/index.js` | `fbb9c34a7e26404f61a54e8157ad4ac41698df3bf298411cf47580f3212abdb3` |
| `out/renderer/index.html` | `6e2c519af0c1c3d80a1ceaaca927a16973c308844cd43a70f760b149bc31c504` |
| `out/renderer/space.html` | `e04665d71c232152d3296693e8a37dcf845a4acff52c73b886f4174d62f28a5f` |
| `out/renderer/assets/PreservedBranchBatchReviewModal-BNcfT7VA.js` | `6fddf7b9ee3d569f8e53198921fe3e0314a2e49e8bd15538833b2d3068503282` |
| `out/renderer/assets/space-C6xO8X8D.js` | `7538a8317c016e37203a4e6a3a2000a186a5e6156ced3e1798e0ea62e0597b5a` |

以 `e2e` 模式构建 Main、Preload 和 Renderer，Windows x64 运行 Electron 43.8.6。配对回放用 Git 2.55.0.windows.5、两个进程及独立档案，参数为 `--space-remote-branches`。Ubuntu WSL 2 内用 Git 2.34.1、一次性 Linux 仓库及 Windows 隐藏 Space，以 `PORPITA_SPEC_WSL_DISTRO=Ubuntu` 运行 `--space-branch-review --space-checkout-drift --space-checkout-inspection`。这份完整回放构建也复跑了第 63–65 轮 Windows 本机入口。 [本轮回放](evidence/README.md#第-6668-轮)

当前 HEAD 把保留分支通知加载移到实际远端保留分支出现后，并修正配对隔离测试夹具。重建 Renderer，Main 和 Preload 复用上表文件。

| 当前 Renderer 文件 | SHA-256 |
| --- | --- |
| `out/renderer/index.html` | `dba8dc2149ebe7ddfddce624980f7f4fab8967ce028d5613eecf52c6a7118a5c` |
| `out/renderer/space.html` | `991872cd7b699c69b477176020bfa7fefd810365423ba55fe8fb7d5cfb25bf2d` |
| `out/renderer/assets/PreservedBranchBatchReviewModal-fBP2mIj7.js` | `f0f59c93a5df4a46d7cfea9295860db651f2f6df9a6e9b70ac659e327cb9860a` |
| `out/renderer/assets/space-DkstRvqN.js` | `5c0c1358e2ffa148f448bbb2c3c3e45aef250109f5b5699725ddba844fbb25d3` |

当前 Renderer 的英语配对回放完成五步。覆盖矩阵绑定当前 HEAD，并保留各运行记录对应的构建身份。 [当前配对回放](evidence/iteration-66-68-paired-head-en/run.json) · [覆盖核对](coverage-audit.json)

提交检查、Node 与 Web 类型检查通过。Node 检查 18,353 个文件，Web 检查 15,530 个文件。分批运行七个聚焦测试文件，56 项通过，三个符号链接用例跳过。配对测试包括旧保留分支的清理请求在配对替换时被拒绝。覆盖矩阵核对为 20 个功能域、350 个唯一条目。

## 第 69–71 轮来源

用户确认第 66–68 轮。Porpita 隔离工作树在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03`，从 `5e7ed685d13c20e0258a861901f621b81dcfde46` 接续。全组回放对应 `a3be0e771dd996011ac97a63017c6264faa66406`，tree 为 `785c6f9ed8a88652e0927659139eba9696e6e22d`。本地分支 `codex/porpita-ui-spec-69` 的当前 HEAD 为 `5f97010d9a4784a34c0e0035d0ff7e2010117c59`，tree 为 `aa2934fe2ea31647140f6ad97165c243c4545f71`。当前提交使 SSH 设置工具栏按空间换行，并补齐配对重连的公开类型。

| 开发构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `b2ab191bb5e5c7751615d9f1c69cf303bf624736afeb804efcb72432d778198a` |
| `out/preload/index.js` | `fbb9c34a7e26404f61a54e8157ad4ac41698df3bf298411cf47580f3212abdb3` |
| 首轮 `out/renderer/index.html` | `228d0a8025c69e4bfbf40ecaf76d9fcbb457c9d64df36f8929eb7fe58b9a25b6` |
| 当前 `out/renderer/index.html` | `8f079343fad822a2155443866e36b2c4e798876d1c3ba5b6432726fc2b291417` |
| 当前 `out/renderer/assets/Settings-CHFfMoI-.js` | `9b5db2393ce8dde3a8a42b7c686e2fdc68d82be0b38258f632af967d8f1ef217` |
| `out/renderer/space.html` | `b7df23078cc10a751b368abd06b506544896541c3fc3fa43a232f2963189e920` |
| `out/renderer/assets/PreservedBranchBatchReviewModal-CEXWd9gi.js` | `2d926bd20e22e8808ee18136f3e212f9d2f87016827d5b88bee5c63f392d4843` |
| `out/renderer/assets/space-BHJvb5Tp.js` | `34ca72a59add57c9a54b4f5bf548ae3ab5dc46a4caa1eb024497a84855c063c3` |

Windows x64 的开发回放使用 Electron 43.8.6。配对恢复采用 `--space-remote-branches --space-recover-branch`。独立 SSH 的 Renderer 回放采用 `--space-ssh-recovery`，当前宽窄复验追加 `--space-ssh-check-layout`。WSL 2 夹具使用 Git 2.34.1，按 `PORPITA_SPEC_WSL_RECOVERY_FIXTURE` 绑定单独启停的发行版，再用原 Space 回放参数操作。 [配对](evidence/iteration-69-71-paired-en/run.json) · [SSH 宽窄复验](evidence/iteration-69-71-ssh-layout-zh/run.json) · [WSL](evidence/iteration-69-71-wsl-zh/run.json)

已登记 Linux x86_64 工作站的 Git 2.43.0 通过 OpenSSH 另行采样。该证据覆盖实机分支、检出路径和引用保留。配对 Renderer 的进程范围为本机回环。 [实机 Git 断言](evidence/iteration-69-71-physical-ssh/physical-ssh-checks.json) · [第 69–71 轮证据](evidence/README.md#第-6971-轮)

全组源码提交检查通过。分支删除、WSL 状态门控、分支复核以及主机连接聚焦测试共 25 项通过。当前 HEAD 的 Node 和 Web 类型检查通过，分别检查 18,354 和 15,530 个文件。覆盖矩阵核对为 20 个功能域、353 个唯一条目。 [覆盖核对](coverage-audit.json)

## 第 72–74 轮来源

用户确认第 69–71 轮。首轮部署沿用 Porpita 基线 `5f97010d9a4784a34c0e0035d0ff7e2010117c59`。实机回放发现 SSH 连接重置无法触发保留分支的行内重连，修订为 `7d7a7cbec05531ea5b4c3bbcc706c59b42de17f0`。复验发现成功通知携带旧失败说明和重试入口。本地分支 `codex/porpita-ui-spec-72` 的最终提交为 `6dc5f823007c4808cca606196e03cc1ff38150dd`，tree `1ddbc858a4c537351a2da48ddcd060607e0c5aa0`。最终 Windows 和 Linux 构建使用同一提交，源码分支未推送（`src/main/managed-server/lifecycle/orcad-managed-tunnel-active.ts`、`src/renderer/src/components/sidebar/workspace-actions/deletion/preserved-branch-batch-toast.tsx`；[源码覆盖](source-index/module-coverage.csv)）。

| 产物 | SHA-256 |
| --- | --- |
| Windows 开发构建 `out/main/index.js` | `452238e292346d4467966aa79892657df9c41f04ddcb802387afbbb713e48593` |
| Windows 开发构建 `out/preload/index.js` | `22fd70b2cc746356a5e538958d66645d6f0c26fa6309d553ae10de5d5f3e77a5` |
| Windows 开发构建 `out/renderer/index.html` | `9aad20568038b4f2da2566812ad70834b9aec97a2ba15595bb8849e265c4ea93` |
| Windows 开发构建 `out/renderer/space.html` | `f792e95bf0857bb44228f6b85536851cecd9c80c64da4d640e316283a02ffab5` |
| Linux `orcad/orcad.js` | `2be9049f9bc2c7d62dfa3411dcc6e6b05313f78dfd245402d0e4da543501247f` |
| Linux x64 托管部署模板归档 | `da0e8584f10f8d5b2809f82660169f352e635548c29dfd4c92cfbca3a21a152b` |

验收机 `yue-Precision-3680` 为物理 Linux x86_64，内核 `6.11.0-17-generic`，Git 2.43.0。产物部署于 `/home/changgeng/.local/share/porpita-ui-validation/6dc5f823007c4808cca606196e03cc1ff38150dd`，包含 `orcad` 和随包固定的 Node 24.22.1。版本标记为 `0.1.0+41c16b177c48`。构建使用仓库锁定的 pnpm 12.14.0，准备原生预构建和移动 Web，再运行 `build-orcad-node.mjs --target linux-x64-glibc` 与 `build-orcad-template.mjs --targets linux-x64-glibc`。本次模板使用仓库提供的 `ORCAD_OMIT_AGENT_BROWSER=1` 配置。Linux Electron 安装与图形启动沿用独立的平台验收项。

源工作树的提交钩子、格式和聚焦 lint 通过。SSH 修订通过 18,354 个文件的 Node 类型检查，最终 Renderer 通过 15,530 个文件的 Web 类型检查。连接、恢复、错误分类及分支通知共四组聚焦测试，17 项通过。

### 实机回放环境

Windows 使用 Electron 43.8.6，通过 `ORCA_BACKGROUND_LAUNCH=1` 启动编译后的工作树。运行目录作为 `PORPITA_SPEC_ENTRY`，让 Electron 读取 Porpita 的 `package.json` 版本。回放从可见 Settings 和 SSH 按钮进入，使用只读 Runtime 请求核对服务身份和项目目录。Linux 将运行端的 `.version` 传给启动环境的 `ORCA_VERSION`，配对对照启动回执与实际连接返回的 Runtime ID。

用临时目录准备一次性配对回执、独立 OpenSSH 监听和专用测试项目。回放清单提供验收主机 SSH 别名、测试目录、两个监听端口、独立端点的公钥指纹和私钥路径，以及校验后的 Linux 托管模板与 Node 归档路径。测试项目包含 `main`、较 `main` 多一个提交的 `review-topic` 和其独立工作树。将同一分支导出为 `branch.bundle`，供 Windows 临时 Git 仓库复制引用并对照结果。服务凭据与私钥存放在各自的隔离档案。

设置 `PORPITA_SPEC_SOURCE`、`PORPITA_SPEC_ENTRY`、`PORPITA_SPEC_EXE`、`PORPITA_SPEC_LOCALE=en` 和 `PORPITA_SPEC_PHYSICAL_FIXTURE` 后，运行 `node tools/observe-installed.cjs <证据目录> --space-physical-porpita`。两个通道都经过实际的 OpenSSH 转发。分支断线步骤只切断独立 SSH 通道，直接配对通道继续用于查询。 [回放](tools/observe-installed.cjs) · [清单读取与连接](tools/physical-porpita-connection.cjs) · [步骤及 Git 断言](tools/observe-physical-porpita.cjs)

最终实机回放完成 8 步。结束后关闭临时配对服务和独立 SSH 监听，移除临时授权和 Windows 测试私钥。验收机保留原生运行端、固定 Node 和已校验的 `orcad-template-linux-x64-glibc.tar`。矩阵核对为 20 个功能域、356 个唯一条目。 [运行记录](evidence/iteration-72-74-physical-en/run.json) · [断言](evidence/iteration-72-74-physical-en/physical-porpita-checks.json) · [覆盖核对](coverage-audit.json)

## 第 75–77 轮来源

用户确认第 72–74 轮。Linux 试跑从 `6dc5f823007c4808cca606196e03cc1ff38150dd` 构建。键盘焦点、工作树选择与 SSH 状态修订为 `cffbba55a876a9f5ead48070e730fb8df65c1ce3`。随后修订终端输入状态下的通知快捷键。最终本地分支为 `codex/porpita-ui-spec-75`，提交 `619c37d7487b31aeca8ad5c7bf643cafba746a2a`，tree `16e17b4dfe3619e8e32bdd0db465460309fbfd6f`。两台验收机的 Porpita 版本均为 0.1.0，Electron 为 43.8.6。

Linux 验收机是物理 Ubuntu 24.04.2 LTS x86_64。图形程序使用仓库的 electron-builder Linux 目录目标，部署在 `/home/changgeng/.local/share/porpita-ui-validation/619c37d7487b31aeca8ad5c7bf643cafba746a2a/desktop-linux-x64`。打包日志确认原生依赖、解包的后台服务、随包 Node、PTY 及插件资源。Electron Linux x64 发布 ZIP 使用官方 SHA-256 `1c657678e0701c5d55b18a3fe18cd9e8a0a375c976292fbfb8406ab13a763402` 校验。 [Electron 43.8.6 发布](https://github.com/electron/electron/releases/tag/v43.8.6)

| 验收产物 | SHA-256 |
| --- | --- |
| `porpita` ELF 图形程序 | `35603b02d251e3ac98661fab6b3a9544a6fe999a6b7e01cb08d9ee3b9bbbb5b5` |
| `resources/app.asar` | `e40fc850de733d508fbbd3ebc668362252154b6f20f3c82b11787fa59a78834c` |
| Windows `out/main/index.js` | `452238e292346d4467966aa79892657df9c41f04ddcb802387afbbb713e48593` |
| Windows `out/preload/index.js` | `22fd70b2cc746356a5e538958d66645d6f0c26fa6309d553ae10de5d5f3e77a5` |
| Windows `out/renderer/index.html` | `cea023773e688252553401e4b7bbf6056a4fdf905f1ffe642f8369f389a39de2` |

本地验收包使用仓库允许的单平台目录构建。独立 SSH 接管通过 `ORCA_ORCAD_TEMPLATE_PATH` 使用第 72–74 轮已校验的 Linux x64 托管模板，模板服务版本为 `0.1.0+41c16b177c48`。多架构托管模板与系统发行包沿用发行渠道验收。Windows 使用后台 Electron 运行真实配对端，只在验收机回环绑定反向 SSH 通道。独立 SSH 项目由验收机上另一个 OpenSSH 监听提供。

验收会话使用独立 Xvfb、Openbox、D-Bus、AT-SPI 2.52 与系统 GNOME Orca 46.1。X11 显示为 1280×900，Porpita 可见区为 1060×790。仅在隔离验收会话中使用 `--no-sandbox` 启动用户目录里的程序，验收机的既有桌面和系统沙盒设置保持原状。按键由 X11 与窗口管理器接收，Playwright 读取应用状态和 Git 路由。系统 Orca 输出使用私有 Speech Dispatcher 与 PulseAudio。 [独立会话](tools/linux-native-session.sh) · [Linux 回放](tools/observe-linux-native.cjs) · [Windows 配对端](tools/observe-linux-pairing-peer.cjs)

提交钩子与聚焦格式、lint 均通过。最终源码的五个聚焦测试文件共 16 项通过，Web 类型检查覆盖 15,531 个文件。

最终十步回放核对 Linux 键盘焦点、真实系统播报和两端 Git 引用，保存原生截图及断线语音片段。结束后移除一次性密钥和读屏原始日志，关闭临时监听，保留图形目录和同级的 `ssh-template-linux-x64`。源码修改已在本地提交。 [原生回放](evidence/iteration-75-77-linux-en/run.json) · [Windows Git 对照](evidence/iteration-75-77-linux-en/windows-peer-proof.json) · [覆盖核对](coverage-audit.json)

## 第 78–80 轮来源

用户确认第 75–77 轮。原始 Wayland 对照版本为 `619c37d7487b31aeca8ad5c7bf643cafba746a2a`。本轮最初的回执修订为 `f1282c1456b4a8d78605118855cdc76903fbed19`。最终验收分支 `codex/porpita-ui-spec-78` 的本地提交为 `1c7c37ecc49d07f64bb7d8fa70a9da387653c480`，tree 为 `d7ea702676c44dd82b8ad83bd51fe44aa24950be`。Windows 验收端和 Linux 图形包均为 Porpita 0.1.0、Electron 43.8.6。 [初版回执](evidence/iteration-78-80-wayland-trial/i79-stale-progress-speech.json)

| 验收产物 | SHA-256 |
| --- | --- |
| Linux `porpita` ELF | `35603b02d251e3ac98661fab6b3a9544a6fe999a6b7e01cb08d9ee3b9bbbb5b5` |
| Linux `resources/app.asar` | `cc222b7c2a8f8c00c2b205400de707138ce9f9c0f3a3f0e9dc850514af917e2b` |
| Windows `out/main/index.js` | `452238e292346d4467966aa79892657df9c41f04ddcb802387afbbb713e48593` |
| Windows `out/preload/index.js` | `22fd70b2cc746356a5e538958d66645d6f0c26fa6309d553ae10de5d5f3e77a5` |
| Windows `out/renderer/index.html` | `cf5c4bafea0c27d9663723b5cf7140e930ae50f6589ee2d6d5061f93d4c9b99f` |

Linux 产物部署在 `/home/changgeng/.local/share/porpita-ui-validation/1c7c37ecc49d07f64bb7d8fa70a9da387653c480/desktop-linux-x64`。目录包使用本机缓存的 Electron 43.8.6，经仓库打包校验。SSH 接管加载同级的 `ssh-template-linux-x64`。该模板来自上轮已校验的 Linux x64 托管产物。

同一台物理 Ubuntu 24.04.2 LTS x86_64 主机以 Sway 1.9 软件渲染、1060×790 输出提供独立会话。Sway 禁用 XWayland，Porpita 使用 Ozone Wayland，实测 surface 的 shell 为 `xdg_shell`。工作区按键由合成器的虚拟键盘协议接收，使用标准 US evdev 键码，截图使用合成器 screencopy。 [会话](tools/linux-native-session.sh) · [键码工具](tools/wayland-evdev-key.c) · [wtype 0.4 协议来源](https://github.com/atx/wtype)

系统旧 Orca 46.1 与试用的 48.1 在无 `DISPLAY` 的会话里调用 X11 修饰键初始化后退出。本轮使用解包到私有目录的 GNOME Orca 51.1 与 AT-SPI 2.62.1，D-Bus、运行目录及语音输出均独立。Orca 包为 `orca_51.1-1~bpo13+1_all.deb`，SHA-256 为 `56455bdf5d73297060f5eb9172fd47af53e485fc365e67593279c1ffdccdd5c9`。应用验收仍使用英语浅色，其他 Wayland 合成器与桌面环境有各自的验收范围。 [Orca 发行包归档](https://deb.debian.org/debian/pool/main/o/orca/) · [AT-SPI 发行包归档](https://deb.debian.org/debian/pool/main/a/at-spi2-core/)

提交检查、三个聚焦测试文件共十一项测试、覆盖 15,531 个文件的 Web 类型检查通过。 [覆盖核对](coverage-audit.json)

最终十四个检查点通过。Linux 与 Windows 的分支结果已交叉核对。回放后关闭临时监听，清除一次性密钥和读屏原始日志，保留校验后的 Linux 图形包与同级模板。 [原生回放](evidence/iteration-78-80-wayland-en/run.json) · [Windows Git 对照](evidence/iteration-78-80-wayland-en/windows-peer-proof.json)

## 第 81–83 轮来源

用户确认第 78–80 轮。沿用 Porpita 0.1.0、Electron 43.8.6 和源码 `1c7c37ecc49d07f64bb7d8fa70a9da387653c480`。Linux 图形目录包与 x64 SSH 模板沿用前轮，对 `app.asar` 重新核对 SHA-256 `cc222b7c2a8f8c00c2b205400de707138ce9f9c0f3a3f0e9dc850514af917e2b`。Windows 对端仍使用同一提交的桌面开发构建。

物理 Ubuntu 24.04 x86_64 验收机使用独立 GNOME Shell 46.0 / Mutter 46.2，虚拟显示输出 1440×900。GNOME Shell 以 Wayland 合成器运行，禁用 XWayland，使用私有 PipeWire 和 WirePlumber 策略输出合成帧。Mutter 接收 US 键盘的 evdev 键码。GNOME Orca 51.1 使用独立 AT-SPI 2.62.1 和 Speech Dispatcher。 [Mutter](https://gnome.pages.gitlab.gnome.org/mutter/) · [独立会话](tools/linux-native-session.sh) · [Mutter 输入与取帧](tools/gnome-wayland-control.py)

首次启动试跑出现 GNOME 的「创建密钥环」系统对话框。最终回放在私有用户目录初始化默认已解锁的临时登录密钥环，通过真实 Secret Service 继续测试进入桌面后的键盘和读屏路径。

接管使用本轮唯一的 SSH、项目与工作树标识。试跑复用旧项目 ID 时返回了历史夹具路径，回放在执行 Git 前停止。最终接管以现有项目 ID 和实际 Git 路径共同核对范围。

同一开发分支的 Linux 图形包通过 21 个原生检查点。客户端在显示器上从 1440px 最大化宽度平铺到 720px。实机目录中还显示历史验收项目，最终操作已核对唯一项目 ID 与本轮实际 Git 路径。归档后关闭测试进程和临时监听，撤销 SSH 授权，清除临时密钥环和原始读屏日志。 [密钥环试跑画面](evidence/iteration-81-83-gnome-trial/startup-keyring-prompt.png) · [运行记录](evidence/iteration-81-83-gnome-en/run.json) · [对端证明](evidence/iteration-81-83-gnome-en/windows-peer-proof.json)

## 第 84–86 轮来源

用户确认第 81–83 轮。基线为 `1c7c37ecc49d07f64bb7d8fa70a9da387653c480`。修订使用本地分支 `codex/porpita-ui-spec-84`，最终回放来自提交 `97a402fc775e8ccdee864555d0d92c4cf6271ba3`，tree 为 `ce2d09a8aae969ca4a70b26c19c652c1d02b5e19`。中间试跑来自 `344cc8e088e2cd13cf927678f0a3f66c5ca60cb7`。 [基线](evidence/iteration-84-86-gnome-baseline/run.json) · [首次连接回执](evidence/iteration-84-86-gnome-trial/i86-connected.json)

Porpita 0.1.0 与 Electron 43.8.6 在同一物理 Ubuntu x86_64 验收机重建为 Linux 目录包，部署在 `/home/changgeng/.local/share/porpita-ui-validation/97a402fc775e8ccdee864555d0d92c4cf6271ba3/desktop-linux-x64`。仓库打包校验通过，连接验证沿用同级已验收的 x64 托管模板。

| 验收产物 | SHA-256 |
| --- | --- |
| Linux `porpita` ELF | `35603b02d251e3ac98661fab6b3a9544a6fe999a6b7e01cb08d9ee3b9bbbb5b5` |
| Linux `resources/app.asar` | `39415f57f967c0f91788d9ca2696e2fb49592b1334f2bdf788f04f158dcf1f87` |

使用 GNOME Shell 46.0 / Mutter 46.2、GNOME Orca 51.1、AT-SPI 2.62.1、US 键盘布局和英语浅色。Mutter 在 1440×900 的独立 Wayland 输出上完成最大化和平铺，应用可见区为 1440×868 或 720×868。三个临时 OpenSSH 监听分别使用三个回环 IP 与非默认端口，主机密钥预先登记。监听日志用来核对 TCP 到达与真实公钥认证。 [会话](tools/linux-native-session.sh) · [回放工具](tools/observe-gnome-ssh-host-choice.cjs)

最终修订通过提交钩子、三份聚焦测试中的 9 项及 Web 类型检查。更新按钮定位的四份 Docker E2E 文件通过用例发现，实机 GNOME 验收走本轮的真实 OpenSSH 夹具。

基线四个检查点和修订版八个检查点已归档。回放完成后，三个回环监听和隔离桌面已关闭，一次性 SSH 授权、临时密钥环和原始读屏日志已清理。 [最终运行](evidence/iteration-84-86-gnome-en/run.json)

## 第 87–89 轮来源

用户确认第 84–86 轮。基线为 `97a402fc775e8ccdee864555d0d92c4cf6271ba3`。最终回放来自本地 `codex/porpita-ui-spec-87` 的提交 `df72b79763023cbb84724c37c5ba4fcb435303fd`，tree 为 `ad76a95aedc57e8963ac1ad22d099c595929ccf4`。Porpita 0.1.0 和 Electron 43.8.6 在物理 Ubuntu x86_64 验收机重建为 Linux 目录包。图形包及 x64 SSH 托管模板保存在验证目录。 [基线运行](evidence/iteration-87-89-gnome-baseline/run.json) · [修订运行](evidence/iteration-87-89-gnome-en/run.json)

| 产物 | SHA-256 |
| --- | --- |
| Linux `porpita` ELF | `35603b02d251e3ac98661fab6b3a9544a6fe999a6b7e01cb08d9ee3b9bbbb5b5` |
| Linux `resources/app.asar` | `fe029ab60cadd5ec4d0ff22dd2810a12616767ee58fbdaf58461e11207da4bf1` |

沿用 GNOME Shell 46.0 / Mutter 46.2、GNOME Orca 51.1、AT-SPI 2.62.1、US 键盘布局和英语浅色。应用在 1440×900 的独立输出中平铺，取样视口为 720×868。三个 OpenSSH 监听各有非默认端口和独立 Ed25519 主机密钥。配置和信任记录均在测试档案内。

基线五个检查点记录了 `ask` 下的直接认证。原采样读取了错误的档案子目录，补录从实际落盘的 `profiles/local-default/ssh-host-keys.json` 提取该地址的公开指纹。最终探针使用正确路径核对确认前、取消后、确认后与重连四个阶段。 [基线落盘记录](evidence/iteration-87-89-gnome-baseline/host-key-store.json) · [实际握手回放工具](tools/observe-gnome-ssh-host-choice.cjs)

最终九个检查点、提交钩子和 Node/Web 类型检查通过。十份聚焦测试中 177 项通过，另有两项依平台条件跳过。归档后关闭三个临时监听和隔离桌面，撤销一次性 SSH 授权，清除临时密钥环及读屏原始日志。 [最终实机检查点](evidence/iteration-87-89-gnome-en/run.json)

## 第 90 轮来源

用户确认第 87–89 轮范围后，本轮（Milestone M1-A：F01 & F02）在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-90`（依次经 `5c8531bc19d794da8736ea6035437bbb40c74c7a` → `28c8847a988e65d8dcac30a3fff5c4301f08844d` 迭代修订）提交最终修订，提交为 `492ba96e45b9f398bbbde0a2dd81b1f88a74d32c`，tree 为 `d42dd8272edb4a9d47e0b93dd5aefce227aa983d`。最终修订在最终 `lint-staged` / `oxfmt` 格式化后重建 `out/`，已通过 `lint-staged`（`oxlint`、`ast-grep`、`oxlint-react-doctor`、`oxfmt`）、五工程并行类型检查（15,538 / 4,186 / 18,357 / 12,988 / 38 文件零报错）、本地化目录校验（21,902 条引用、`zh.json` 18,724/19,558、`en-runtime-required.json` 2,775/19,558）及 49 份聚焦 Vitest 测试文件（48 份通过 / 265 项通过；1 份按 `process.platform === 'win32'` 条件跳过）。

| 默认生产构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `428709ea31a9f0625c8aab3bcc34d04465556fdf32c27ef9e9862a3f06eea292` |
| `out/preload/index.js` | `22fd70b2cc746356a5e538958d66645d6f0c26fa6309d553ae10de5d5f3e77a5` |
| `out/renderer/index.html` | `0d600c2f5d73100f64a9a3a3b4892ceef034ab630642b90ba11c825898a522b5` |

Windows x64 使用默认生产模式构建与 Electron 43.8.6，在 `ORCA_BACKGROUND_LAUNCH=1`、`ORCA_E2E_HEADLESS=1` 及隔离临时 `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA` 档案下运行 `tools/observe-round-90.cjs`（所有窗口核验 `!visible && !focused`），采集 23 组英/简中宽窄屏截图及状态记录（含 Skip 确认取消焦点恢复至 `Continue` 按钮、英语 Help 菜单 `Explore Porpita` / `Getting Started with Porpita`、以及 `TerminalSlide` 简中终端示例画面）。未配置账户云端服务与物理手机端实机扫面继续在各自边界下保持诚实待验。 [第 90 轮记录](ITERATION_90.md) · [回放工具](tools/observe-round-90.cjs) · [运行记录](evidence/iteration-90-windows/run.json) · [覆盖核对](coverage-audit.json)

## 第 91 轮来源

第 91 轮（Milestone M1-B：F03 视觉/基础组件/动效/可访问性与受控 `<Dialog open>` 回焦）在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-91` 开展（基于 `50a1e8645a98d9951182ac3d04bee77290a710d6`），最终提交为 `e8062ab946c15a1afd57a78f51d3199b7f2e151d`（tree `f57f1b5f071580832c69589a3d51fddf1c0adf19`，涵盖 32 项文件改动：27 项修改、1 项删除旧测试 `main-css-accessibility-motion.test.ts`、4 项新增：`SettingsSegmentedControl.tsx`、`dialog-return-focus.ts`、`dialog-return-focus-targets.ts`、`dialog-return-focus.test.tsx`）。`@porpita-ui` 报告并在提交钩子（`.husky/pre-commit` `lint-staged`、`oxfmt`、`oxlint`、`ast-grep`、`oxlint-react-doctor`）验证通过：`check-changed-code-quality.mjs`（基线 `492ba96e45` 44 个变更文件与 `50a1e8645a` 24 个变更文件均 0 新增报错，含 `anti-slop`、`shadcn(no-restyle)` 与 `design system`）、`check:test-file-runners`、`oxfmt --check`（30 项）、5 工程并行 `corepack pnpm tc`（`15,543` / `4,186` / `12,991` / `38` / `18,357` 文件）、16 份 Vitest 回归（73 项通过）以及 `--mode e2e` 构建；`@verifier` 独立复核并复测通过（含 `--tier all --mode smoke` `total=87 passed=59 pendingMilestone=28 failed=0`）。

| `--mode e2e` 构建文件 | SHA-256 |
| --- | --- |
| `out/main/index.js` | `47d1129ad627295542fb06275f8feac51067f9dd09da09a4681c1faf524a33de` |
| `out/preload/index.js` | `d9bd4929c1e139efe173b7148c87d92a8f9f75d29ac945399049cc0d5c92b809` |
| `out/renderer/index.html` | `91d430b52b5a8cbb399dba675146d343c43307116c6c8d58f7a789d1a2080469` |

Windows x64 使用 `--mode e2e` 构建与 Electron 43.8.6，在 `ORCA_BACKGROUND_LAUNCH=1` 与临时隔离档案下运行跨平台升级版 `tools/observe-round-91.cjs`（所有窗口核验 `!visible && !focused`），采集 `evidence/iteration-91-windows/` 下 9 组截图与状态 JSON：验证 `AddRepoDialog` 在 `reduced-motion: reduce` 下的 `Local Windows` 焦点环与 `Escape` 精准回焦主区 `Add project` 按钮、Light/Dark `ArrowLeft` 切换保持 `scrollTop=120`、`System` 实时跟随 `prefers-color-scheme`、`forced-colors: active` + `prefers-contrast: more`、`158%` UI 缩放（未裁切 `1280×800` CDP 截图，CSS 视口 `811×507`）、`820×580` 与 `600×400` 极窄窗无碰撞、Settings 折叠箭头 `0s` 过渡以及 `en → zh → ja` 无重启实时切换。真实可见桌面窗口下的 `WindowMaterial` OS 材质合成、物理读屏器与 macOS/Linux 复测保持在各自受限边界外待验。 [第 91 轮记录](ITERATION_91.md) · [回放工具](tools/observe-round-91.cjs) · [运行记录](evidence/iteration-91-windows/run.json) · [覆盖核对](coverage-audit.json)

## 第 92 轮来源

第 92 轮（Milestone M1-C：F04 `H.*` Git / Diff、`I.*` Browser、`L.*` Skills / Plugins、`N.*` Settings 专题与 `O.*` 引导/弹窗）在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-91` 开展（基于第 91 轮提交 `e8062ab946c15a1afd57a78f51d3199b7f2e151d`），最终提交为 `d874c87b6c5a1115667f89b15dac78640b3c8568`（tree `0c64fea467ed43f1f802d6fd41dc36297ae11606`，`ui(f04): complete Round 92 plugin runtime, browser find, git graph, narrow toolbar, and overlay polish`，涵盖 `42` 项文件改动：34 项修改、8 项新增：`plugin-frame-guest-sessions.test.ts`、`StarNagCard.escape.test.tsx`、`BrowserFind.test.tsx`、`RepositoryRemoveProjectButton.test.tsx`、`use-effective-workspace-sidebars.ts`，以及为保持组件单文件 `<=400` 行而拆出的 3 项同级 Hook：`use-browser-address-bar-input-keydown.ts`、`use-browser-page-viewport-element-sync.ts`、`use-plugin-switch-focus-recovery.ts`）。`@porpita-ui` 报告并在提交钩子（`.husky/pre-commit` `lint-staged`、`oxlint`、`oxlint-js-plugins`、`ast-grep`、`oxlint-react-doctor`、`oxfmt`）验证通过：`oxfmt --check`（42 项）、`oxlint`（37 项 `.ts`/`.tsx` 0 告警 0 报错）、`check-changed-code-quality.mjs e8062ab946`（37 个变更文件 9 项扫描均 0 新增发现）、`check:has-restyle-scope`（15 份样式表）、`verify:localization-catalog`（21,915 条引用校验）、5 工程 `corepack pnpm tc`（0 错）、21 份 Vitest 回归（109/109 项通过）以及 `build:packages` + `--mode e2e` 构建（24.11s）。`@e2e-harness` 于最终 Hook 拆分前等效 `out/` 完成全量 Phase 2 E2E 回归：`18/18` `--mode full` PASS（`T1-F04-01..06` `porpita-e2e-report-1795296087841.json`、`T2-F04-01..06` `porpita-e2e-report-1795296457185.json`、`T3-06` `1795296537396`、`T3-07` `1795296604221`、`T3-08` `1795296713832`、`T4-01` `1795296851935`、`T4-03` `1795296992349`、`T4-05` `1795297059922`）及 `--tier all --mode smoke` `total=87 passed=59 pendingMilestone=28 failed=0 overall=PASS`（`porpita-e2e-report-1795300061232.json`），归档后于最终提交 `d874c87b6c` 复验受影响用例。

| `--mode e2e` 构建文件（`d874c87b6c`） | SHA-256 |
| --- | --- |
| `out/main/index.js` | `c9f1df1f0d2584fec21996e783e325fa007dd92072ed055ce9e8490e2969aa5e` |
| `out/preload/index.js` | `d9bd4929c1e139efe173b7148c87d92a8f9f75d29ac945399049cc0d5c92b809` |
| `out/renderer/index.html` | `b07628e2f447e593a8da9be9d0859a482227aa7e7007b23a602be9e784336b9a` |

Windows x64 使用最终提交 `d874c87b6c` 的 `--mode e2e` 构建与 Electron 43.8.6，在 `ORCA_BACKGROUND_LAUNCH=1` 与临时隔离档案下运行跨平台 `tools/observe-round-92.cjs`（先期基线对照诊断于入库前已清理，仅保留最终严格门禁 `evidence/iteration-92-windows/`）：19 组严格门禁全过（`findings: []`、退出码 `0`）且 19/19 人工视觉复核通过。未配对云服务下的在线插件源/Automations 远端调度、Chrome Web Store 扩展安装（`I.04`）、远端 SSH/WSL 大文件审阅写回、可见桌面前台切换、物理读屏器与 macOS/Linux 三端继续保持在各自边界外待验。 [第 92 轮记录](ITERATION_92.md) · [回放工具](tools/observe-round-92.cjs) · [严格终版运行](evidence/iteration-92-windows/run.json) · [覆盖核对](coverage-audit.json)

## 第 93 轮来源

第 93 轮（Milestone M2：F05 + F06 ACS 协作长驻状态同步、术语对齐、核心全链路与故障核查恢复）在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-91` 开展（基于第 92 轮提交 `d874c87b6c5a1115667f89b15dac78640b3c8568`），最终提交为 `1b27aeb1142a98ba4ac5aae1be711d441a42f9f8`（tree `f347474c0887bd9df3cf3da81df4c1bffbaa8dbe`，`ui(f05,f06): complete Round 93 collaboration state sync, copy unification, and loopback UX`，涵盖 `31` 项文件改动：含新增 `collaboration-connection-sync.ts`、`communication-view-sync.ts`、`communication-view-state.ts`、`communication-view-transport.ts`、`CollaborationSearchResults.tsx`、`collaboration-connection-sync.test.tsx`、`CollaborationDialogFlows.test.tsx` 与 `collaboration-test-fixtures.ts`）。`@porpita-ui` 在提交钩子（`.husky/pre-commit` 含 `oxlint`、`oxlint-js-plugins`、`ast-grep`、`oxlint-react-doctor`、`oxfmt`）与代码门禁验证通过：`check-changed-code-quality.mjs d874c87b6c`（26 个变更文件 9 项门禁均 0 新增发现）、`git diff --check HEAD~1..HEAD`（退出码 0）、5 工程 `corepack pnpm tc`（`15,558` / `4,186` / `18,358` / `38` / `12,991` 文件 0 错）、5 份 Vitest 回归（16/16 项通过）以及从提交树执行的 `build:packages` + `--mode e2e` 构建（23.06s）。`@e2e-harness` 亦于 `#155` 等效 `out/`（`Agent-collaboration` `AC_WORKTREE` `3af1e5b18fd47c7b4a5a1651b7eb55487cde778c`）完成全量 Phase 3 E2E 回归：`15/15` `--mode full` PASS（`T1-F05-01..06` `porpita-e2e-report-1795315933779.json`、`T2-F05-01..06` `porpita-e2e-report-1795316077360.json`、`T3-05` `1795316153163.json`、`T3-06` `1795316231970.json`、`T4-04` `1795316342739.json`）及 `--tier all --mode smoke` `total=87 passed=60 pendingMilestone=27 failed=0 overall=PASS`（`porpita-e2e-report-1795319424820.json`），提交后再由 `@e2e-harness` 复验 `T1-F06-01` 与 `T1-F05-01`。

| `--mode e2e` 构建文件（`1b27aeb114`） | SHA-256 |
| --- | --- |
| `out/main/index.js` | `78ede9142487d0c2e8154112da82a632fbe44fc13fbe57f8410b10b39e76bc26` |
| `out/preload/index.js` | `d9bd4929c1e139efe173b7148c87d92a8f9f75d29ac945399049cc0d5c92b809` |
| `out/renderer/index.html` | `482bf82c531fc5f0e8378a75586f388b37b6f4595d64dc7e66fdc7d6bc208b7e` |
| `out/renderer/assets/index-h_2cRRs9.js` | `a1fc84178de1fd6b1c52b228d50ebe8816885f868ecd132703149ca20704e962` |
| `out/renderer/assets/App-ueB-kzW5.js` | `dca66211f70cd1a67138ae53ee46a22486953a6232de6c3b725e06af2bc6fd1b` |
| `out/renderer/assets/Settings-DK9ZhbPM.js` | `5864672373fdc7f6976369dfe6dfd69f359d2345011b20ef4d402d302064a1ed` |

Windows x64 使用最终提交 `1b27aeb114` 的 `--mode e2e` 构建、Electron 43.8.6、临时 PostgreSQL 16 隔离回环 `acs_loopback_server.py`（`mode: 'full'`）与 `ORCA_BACKGROUND_LAUNCH=1` 运行跨平台 `tools/observe-round-93.cjs`：12 组严格门禁全过（`findings: []`、退出码 `0`）且 12/12 人工视觉复核通过。真实跨物理 Host 远端 HTTPS/TLS 部署、真实在线 Claude/Codex 远端 Native 执行流式长链路、可见桌面前台切换、物理读屏器与 macOS/Linux 三端继续保持在各自边界外待验。 [第 93 轮记录](ITERATION_93.md) · [回放工具](tools/observe-round-93.cjs) · [严格终版运行](evidence/iteration-93-windows/run.json) · [覆盖核对](coverage-audit.json)

## 第 94 轮来源

第 94 轮（Milestone M3 / Phase 4：F07 默认生产构建一体集成与 F08 工作区／会话目录收口）在 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-ui-spec-03` 的本地分支 `codex/porpita-ui-spec-91` 开展（基于第 93 轮提交 `1b27aeb1142a98ba4ac5aae1be711d441a42f9f8`），最终提交为 `ab899ffee48ff6263a2422b96e59d24a06c2d436`（tree `a7c5abba9e212d36f55d6a0769212aa0b24c6152`，`feat(workspace): integrate unified workspace chrome and F08 session controls`，涵盖 `42` 项文件改动，`+2289/-448`）。工作树通过 `.husky/pre-commit`（`lint-staged`）与仓库门禁（`oxfmt --check`、`oxlint --deny-warnings`、`check-changed-code-quality.mjs 1b27aeb1142a` 0 新增发现、`verify:localization-catalogs`、`corepack pnpm tc` 5 套配置 0 错误、Vitest 9 套件 39/39 通过），并由提交树重新执行 `electron-vite build --outDir out --mode e2e` 生成纯净无预览门控构建。`@e2e-harness` 亦于 `D:/Chatgpt/Agent-collaboration/.tmp/porpita-e2e-suite` 与 `AC_WORKTREE` 同步镜像（`SYNC_DIFF=0 FILES=13`）完成 M3/F01/F03 28/28 `--mode full` PASS（`T1-F01` 6/6、`T1-F03` 6/6、`T2-F01` 6/6 含 `T2-F01-06` 最终加固复通、`T2-F03` 6/6、`T3-02..04` 3/3、`T4-02` 1/1）及全量 `--tier all --mode smoke` `total=87 passed=84 pendingMilestone=3 failed=0 overall=PASS`（余 3 项属 M4 预留 `T1-F06-03`/`T1-F06-04`/`T4-06`）。

| `--mode e2e` 构建文件（`ab899ffee4`） | SHA-256 |
| --- | --- |
| `out/main/index.js` | `f738854937911ef383a7843ff3b3fd6e33d24842415f9b88b45bd0de76bea93a` |
| `out/renderer/index.html` | `9cf32fde3e799ccc10b209211872e77086a9a5d9e2f6567394d49f6dcd59bb1f` |
| `out/renderer/assets/App-BQAcjRgX.js` | `0431996cdf1a18359da9f118a9b709ea7166a7884d0ddf699717af96f75101ed` |

Windows x64 使用最终提交 `ab899ffee4` 的 `--mode e2e` 构建、Electron 43.8.6、`ORCA_BACKGROUND_LAUNCH=1`（全部 `!visible && !focused`、显式剥离 `VITE_PORPITA_WORKSPACE_PREVIEW`）运行跨平台 `tools/observe-round-94.cjs`：13 组严格门禁全过（`findings: []`、退出码 `0`）且 13/13 人工视觉复核通过。真实在线模型流式、物理多机配对断线／撤权切换（归 M4 Phase 5）、系统可见前台窗口、物理读屏器与 macOS/Linux 三端继续保持在各自边界外待验。 [第 94 轮记录](ITERATION_94.md) · [回放工具](tools/observe-round-94.cjs) · [严格终版运行](evidence/iteration-94-windows/run.json) · [覆盖核对](coverage-audit.json)

## Phase 5（F09 / F10）跨文档与结构化证据对齐

Phase 5（Milestone M4）继续锁定上述 Porpita 源码基线 `ab899ffee48ff6263a2422b96e59d24a06c2d436`（tree `a7c5abba9e212d36f55d6a0769212aa0b24c6152`），无新增源码构建改动；`coverage-audit.json` 与 `source-index/` 重新基于同一提交核算并保持零误差。文档侧建立跨规范双向索引：
- [ORCA-FIRST.zh-CN.md](../ORCA-FIRST.zh-CN.md)：保留原第 1–10 节历史基线及第 9 节原位归档（**5 份旧 `.zh-CN.md`、3 份 `.html` 与 3 个归档目录维持零字节改动**），新增第 11 节将全部 `T01`–`T12` 与 `UX01`–`UX22` 双向映射至 `porpita-ui-spec/`；
- [DECISIONS_AND_SEQUENCE.md](DECISIONS_AND_SEQUENCE.md)：补全参考包 11 项交付物、全部 `Open #1`–`#12` 开放问题、以及 [communication-openapi.yaml](../communication-openapi.yaml)、[communication-p1-openapi.yaml](../communication-p1-openapi.yaml)、[communication-api-scope.json](../communication-api-scope.json) 与 [communication-contract-adoption.json](../communication-contract-adoption.json) 的对照映射；
- [.ui-spec/design-evidence.json](../../../.ui-spec/design-evidence.json)：按 `ui-spec-evidence/1` 格式建立全量设计对象、证据与边界索引，并通过 `check_design_evidence.py` `overview` / `detail` / `execution` 全视图检查。

## Phase 6（M5）全量 `--mode full` 验收与 Stage 6B 终版对齐

Phase 6 Stage 6A 在 `ab899ffee48ff6263a2422b96e59d24a06c2d436`（`--mode e2e` 构建）与 `da956c6cf09c94cbf9553f4d113d37c3aa12510f` 上完成 `node run-e2e.mjs --tier all --mode full` 全量验收：**`total=87 passed=87 pendingMilestone=0 failed=0 passed=true`**（`Tier 1: 36/36`、`Tier 2: 36/36`、`Tier 3: 8/8`、`Tier 4: 7/7`）。

Stage 6B 在 `codex/porpita-ui-spec-91` 经 `0d285b0e5f98a5a672847f7ea56e08ffaf63c5ad`（7 项国际化／翻译订阅／静态导入精确清理）后追加局部 IPC 缺失回退修复，生成最终发布基线提交 **`3f30f4d81a6e0da0cbdde74025f0db30baf1d5b6`**（tree `9a3e1fb5400fe270f1ad0c0bbd7ef9ec0c76a029`：`workspace-preview-persistence.ts` 在 `window.api?.ui?.readPorpitaWorkspaceLayout` / `writePorpitaWorkspaceLayout` 未注入的局部 mock 场景下安全回落并保持 `readPorpitaWorkspaceLayout` reject 时 `readFailed: true`，配套 `workspace-preview-groups.test.ts` 新增回归测试），并通过 `corepack pnpm tc`（5 配置 0 错）、`verify:localization-catalogs`（21,925 条引用）、`check-changed-code-quality.mjs 50a1e8645a`（0 新增发现）、`app-shell/` + `workspace-preview/` Vitest 14 套件 48/48 通过、提交后定向 Vitest 2 套件 9/9 通过、默认 `corepack pnpm exec electron-vite build`（退出码 `0`）以及最终 `--mode e2e` 重建；`source-index/` 与 `coverage-audit.json` 已重新核算并绑定至 `3f30f4d81a6e0da0cbdde74025f0db30baf1d5b6`。

| Stage 6B 最终 `--mode e2e` 构建文件（`3f30f4d81a`） | SHA-256 |
| --- | --- |
| `out/main/index.js` | `f738854937911ef383a7843ff3b3fd6e33d24842415f9b88b45bd0de76bea93a` |
| `out/preload/index.js` | `b93f9d0cc8a190c5d5831687fd718a030d348de3754bf9776093e56f2ca839d3` |
| `out/renderer/index.html` | `229beebd0316a11b578a999b0422b74ee40740f97c8684deb98fd59216f867a9` |
| `out/renderer/assets/App-B07Nx7kE.js` | `b18ad52fbd4f90b9d8ff9da817ada3d8b5c502d899b75402301a3d113349048f` |
| `out/renderer/assets/app-command-dispatch-CDnAG8lM.js` | `d3d9b080b23e4525a2caebd970db2ae935de953b440a77d32c5e3b547565b58a` |
