# 辅助工具的范围

本目录是交接辅助，不是 Porpita Runtime，不在产品消息热路径运行。

- `validate_package.py`：JSON、ID/依赖、相对链接、清单哈希一致性。
- `inspect_workspace.py --acs PATH --client PATH [--out FILE]`：只读本地Git与已知路径，不fetch/checkout/install。
- `verify_delivery.py delivery-manifest.json --delivery-root DIR`：检查最终记录、必交场景、产物及证据文件。可选安装jsonschema后进行完整schema校验；基本检查只需Python标准库。

完成验收模板填写后，将产物和证据置于同一交付目录内。工具不接受以公网链接代替本地待验证文件。大型安装器使用流式hash。

**验证文件存在，不等于验证其真实性。** 本工具不能辨认截图是否真实、模型是否自主行动或界面是否好用，不能自动证明PRODUCT_ACCEPTED。`tests/`使用的样本是临时合成数据，严格不属于产品证据。

这组脚本不要求Codex增加新的生产校验、日志或状态机；可以直接沿用现有工程工具完成相同记录。
