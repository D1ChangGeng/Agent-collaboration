# 12｜真实构建、安装与交付

## 复用已存在的工具链

本轮核查的 Orca package.json 使用 Electron/Vite、pnpm workspace 和 electron-builder，版本 1.4.214。优先采用仓库已锁定 Node/pnpm/依赖与 native addon 处理，不无故升级大版本。

已核查的脚本入口（执行时读 adopted package.json 复核）：

```sh
pnpm install --frozen-lockfile
pnpm run dev
pnpm run typecheck
pnpm run build:desktop
pnpm run build:win
pnpm run test:e2e
pnpm run test:e2e:headful
```

`build:win` 使用 `config/electron-builder.config.cjs`；其配置含真实原生依赖、daemon、CLI、远端与 web/mobile 资源。不能仅改 productName 后删掉“看起来不需要”的资源使打包通过。配置中 `com.stablyai.orca`、上游 channels/release repo 必须按品牌规范处理。

## 产物

默认首个候选 `Porpita-0.1.0-windows-x64`，输出实际安装器和必要安装资源、SHA-256、版本与两个源码来源。优先复用原 NSIS/平台配置。若已有 Porpita 版本则顺延，绝不冒称为 Orca 1.4.214。

可选本地 portable 便于验收，但不能只交 unpacked dist 目录冒充用户安装交付。目标平台签名缺失时内部候选可明确未签名安装；不关闭 OS 安全机制或虚报签名。公开分发与商用权利、签名凭据另行确认。

macOS/Linux 保留并尽可能构建；没有实际 runner 就写未构建/未验收，不删除平台功能、不伪造跨平台安装证据。首发 Windows 不因已有 Linux CI 容易而被静默换掉。

## Core、SDK 与本地依赖打包

固定 ACS wheel 和已采用 SDK 来源，按清晰模块边界嵌入/复制构建产物，不把 RFC_TEMP_SOURCE 或全部研究证据打入应用。Python/PG 托管依赖随包或经用户同意下载，真实来源/version/平台/hash 在 dependency manifest 中记录。最终用户不需要开发 checkout 和环境变量才能用本地模式。

Core 端更新只限必要接口补齐和影响本产品的缺陷修正；按实际源码重新构建，不以历史 2.3.1 wheel 名称代替内容核对。

## CI 与最少充分测试

保留上游相应构建、typecheck、受影响 unit/integration 和现有桌面 smoke。ACS 新服务关键 PG/SDK 套件需要实际执行，别让无 DSN 的 skip 冒充覆盖。旧 CI 的已知夹具问题若仍存在，修 test/environment，不扩展生产逻辑。

单独增加“Porpita product smoke”运行首代核心用户路径。测试真正读写隔离服务和宿主，不使用生产数据。不要求重建数百新机制测试或全平台可靠性研究。

## 最终安装验收

安装到非开发目录 → 从桌面/开始菜单启动 → 设置服务与模型 → 打开真实仓库 → 双 Agent ACS 协作 → 查看原生工具/Diff/审批 → 退出重开 → 历史与工作区恢复 → 卸载不误删用户数据。上述使用同一候选包，不能 build A 的安装器配 build B 的演示。

提交源代码、必要 migration、运行说明和产物，不擅自 push 到上游或执行公网 release。最终能否公开发布与本地产品验收是不同状态。
