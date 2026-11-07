# 测试资料边界

`test_contract_pack.py` 是可以现在运行的开发包一致性测试。`scenarios.json` 是 Codex 必须转化为 ACS 目标系统测试的 96 项工程场景；全部初始状态为 not_executed。它们不是新的产品对比或研究型实验。

```sh
python tools/validate_pack.py --out quality/package-validation.json
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/validate_trace.py fixtures/traces/valid_unknown_with_reply.json
```

负例 `fixtures/traces/invalid_*.json` 必须失败。轨迹检查器只能检查提供的数据与部分不变量，不认证输入轨迹是真的，也不证明 Provider 幂等/真实副作用。

目标项目测试实现应复用 runtime_tests 和原集成证据体系。新 case 必须关联 scenario ID；需要真实 PG/多进程/原生协议/独立模型/宿主的层级不能被此处 unittest 替代。缺少实际环境时写 blocked，不能用 skip 统计为通过。
