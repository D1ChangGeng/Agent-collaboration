# v1.1 范围和证据裁决

| 输入条款 | 本次采用行为 | 实际路径/证据 |
|---|---|---|
| v1.0 WP 线性状态 | 按 C01–C25 当前源码核验；历史状态存档 | adoption-state.json；prior-assessments/ |
| v1.1 默认 P2 可选 | 当前用户明确要求 P2；交付 C22–C25 的全部 13 操作，保留 canonical tier | api-assessment.json；exact-completion-b.xml；p2-initial.xml |
| 旧 T006 要先落 Inbox | v1.1 P0-01 旧 MCP 返回语义优先，保持歧义时提交前拒绝，零广播与显式选择 | test_configuration_selects_one_real_receiver_and_rejects_another_slots_receiver；acceptance-audit.json |
| T031 verified enqueue 前提 | 当前未声明安全原生 enqueue；busy deferred、queue/steer typed unsupported，不将 queued 当 consumed | Native 输入观察/签名 Adapter 回归；qualification-matrix.json |
| P1 等于真实 Orca 接通 | 22 通信服务 + Host 委托/降级合同通过；实际 Host 单独保持未资格化 | P1 headless、SDK210、ui-contract-assessment.json |
| 历史 Native 证据 | e 的 Native/Core-MCP 栈保持；普通 HTTP facade/测试增量经当前组合验证；b/g 的 Core wait 后续变化另列 | retained-native-evidence.json；qualification-matrix.json |
| 普通 read 兼容 | 只在 include_native_source=true 时转交扩展参数，保持默认/false 的旧调用形状；不削弱原续读断言 | runtime/communication_http.py；read-compatibility-final.*；p0-p1-final.* |
| 早期缺 lifecycle/rebind/wake 描述 | 当前实现和签名/TLS/PG 回归已存在，纠正旧台账；原描述归档 | 当前 C05–C07 与 C11；p0-p1-final.* |
| 运行包版本与生产版本 | 同为 2.3.1 的候选由 wheel SHA 和逐文件字节区分，仅临时安装 | package-facts.json；T090 |

没有改动开发包原件、历史失败日志或生产数据。完整原 GWT 保留，只有有证据的
适用行为与修订裁决才标为已核验；不声称 96 个旧 Given/When/Then 原样全通过。
