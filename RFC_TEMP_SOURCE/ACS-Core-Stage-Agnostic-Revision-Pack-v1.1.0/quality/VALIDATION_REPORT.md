# 阶段无关修订包 v1.1.0｜包级静态核验

本报告只证明**交付材料内部一致**；不证明任何 ACS 源码已经按照本版开发，不证明 Orca Host/Driver 已真实联通。

## 设计与范围

- 本版为 v1.0.0 的进度无关修订；`reference/` 原样内嵌上一版 ZIP，使本版自包含。
- 旧版 40 条 R 映射：P0 28 / P1 10 / P2 2。
- 旧版 96 个测试场景映射：P0 63 / P1 26 / P2 7；旧测试 ID 保留。
- 旧版 30 项客户端 UI 能力：P1 26 / P2 4；Host 原生能力仅做 delegated port/降级合同。
- 旧版 35 个 HTTP 操作：P1 22 / P2 13；`contracts/openapi-p1.yaml` 只含 P1 22 个 operationId。
- 新 25 个自主适配改造项：P0 11 / P1 10 / P2 4；所有状态模板均为 `unassessed`。

## 执行的包级检查

1. `python tools/validate_pack.py`：检查旧 ID 全覆盖、唯一性、跨级测试依赖、P1 OpenAPI、可选 P2 DTO 字段、改造依赖无环、状态初值不冒认；详见 `validation-result.json`。
2. `python -m unittest discover -s tests -p 'test_*.py' -v`：5 项包内规则测试（未评估进度、旧成果保留、无证据不能标通过、P2 不阻塞等），详见 `unittest-output.log`。
3. `tsc --noEmit --strict --target ES2022 --lib ES2022,DOM --skipLibCheck contracts/orca_integration.ts`：类型检查通过，详见 `typescript-check.log`。
4. `python -m py_compile contracts/adapter_protocol.py`：Python 参考接口可编译；不代表具体 Adapter 已实现。
5. 最终归档完成后需以 `tools/verify_checksums.py` 对完整文件清单核验，再从解压的归档中重复 1/2/5，避免归档产物不同。

## 仍未执行的验证

- 没有更改用户的 ACS/GitHub 仓库，也没有改 Orca 源码。
- 没有启动、恢复或操作生产 Harness/Node/Session；没有向真实 Agent/用户发送测试消息。
- 没有运行 PostgreSQL 业务回归、Native 独立模型 E2E、真实 Orca Host / UI 接入。
- 所有 P0/P1 工程验收场景都是**Codex 后续实际实施时的门槛**，不是本次包构建的已通过结果。
