# 01｜源码基线与阶段无关接续

## 已核查引用

| 仓库 | 固定参考 | 说明 |
|---|---|---|
| D1ChangGeng/Agent-collaboration | `e5d71968a13e67e3dc51e318867d4ed9a1f946ac` | 本轮观察到的 main；已合并 P0/P1/P2 |
| ACS 改造前历史 | `19d7881d49ee887315c54c5bc02e0cc424061376` | 仅作语义/差异参考，不要求回退 |
| stablyai/orca | `26179069b664b2fc172963564ed419d97892b6c9` | 本轮观察到的 main；package.json 为 1.4.214 |

这些是可复核的参考版本，不是永远最新版本，也不是无条件通过全部构建的认证。上游文件已发生目录整理，使用 references 的当前路径，不机械沿用旧讨论路径。

## 当前 ACS 已有的资产

保留稳定 Client/Slot、Project/Root/Route、自然 send/reply_to/wait、Authority/Outbox、Codex/OpenCode 接收。直接消费 `sdk/communication-client.ts`、`communication-state.ts`、`communication-stream.ts` 和实际已采用 schema。HTTP `/api/communication/v1`、SSE、会话投影、搜索、个人状态、附件不从零开发。

`runtime/orca_receiver_backend.py`、`sdk/orca-receiver-port.ts` 与 Host delegate 是已有桥接基础。实际 Orca Host 仍需接线；把这列为功能开发，不开展第二轮模拟器研究。Native 附件交付历史上未接通，本轮需要宿主可读材料化，不能用后端上传成功冒充模型可用。

## 工作树处理

发现顺序：当前 Porpita 工作树（如有）→ 当前 ACS 工作树 → 用户已准备的 Orca checkout。已知历史 ACS 位置为 `/mnt/d/Chatgpt/Agent-collaboration` / `D:/Chatgpt/Agent-collaboration`，这只是查找线索，不是可写目标假设。

没有 Porpita 时，在与 ACS 分离的工作目录建立派生仓库，默认目录 `Porpita`。保留 `upstream` 指向 Orca；没有用户指定的自有远端时只提交本地，不擅自创建公开仓库。不要复制 Orca 源码进 ACS runtime 包，也不要嵌套覆盖用户已有 checkout。

已有 Porpita 或 Core 改动逐项归并：

| 发现 | 行动 |
|---|---|
| 已实现、同语义且可运行 | 复用；只补本轮受影响路径验收 |
| 部分实现 | 补齐最短缺口，不重置原方案 |
| 与当前明确产品方向冲突 | 局部调整并记录，保留有效代码/数据 |
| 旧接口名称仍使用 Orca | 判断是否内部兼容名称，不一律替换 |
| 新代码尚未合并 | 在现有分支/工作树增量实施，不覆盖 |

ACS 与客户端可分仓提交，用实际 commit + wheel/SDK 内容标识关联。不要仅用仍叫 2.3.1 的包版本推断内容。

## 历史问题如何处理

此前审计发现浅克隆兼容 oracle、旧 fixture 100项列表假设、POSIX 私有目录准备和持续 PG/SDK 测试覆盖问题。它们是参考事实，不等于执行时仍存在。只有仍然影响本次构建/关键路径时修复，优先调整 fixture/CI 取历史，不为测试新增生产防御逻辑。

旧包/审计里“插件优先且是最终产品入口”“Root/Route 显式主导航”“全部环境资格后才开始 UI”等建议已由本包产品决策取代。ACS 消息身份、显式回复、独立通信等核心语义仍保留。
