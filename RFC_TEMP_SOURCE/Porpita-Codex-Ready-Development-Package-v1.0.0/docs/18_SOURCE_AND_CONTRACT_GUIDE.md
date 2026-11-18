# 18｜如何使用机器可读清单与类型

- requirements：30项产品/工程约束，每项有工作包与功能场景。
- feature-parity：28类实际继承/接入能力，不是28个新页面。
- message-paths：14条路径，明确应替换与应保留的通信平面。
- branding-map：15类品牌、服务、合法声明和兼容名称。
- acceptance-scenarios：22个功能性场景，大多数为正常用户路径；不是新一轮探索实验。
- work-packages：10个连续工作包及依赖。
- source-lock：本次核查与历史来源界限。
- desktop-boundary.ts：Porpita薄集成边界的参考类型，不替代ACS已采用wire/schema，也不声称上游已有这些方法。
- delivery-manifest.schema.json：最终交接记录格式，不是产品运行时协议。

这些清单用于避免遗漏实际功能和假完成，不应生成新的生产状态机。实际API/DTO以当前ACS SDK和Host源为准。对已有同等结构可以适配，不要求将参考类型复制进核心领域模型。

执行者可在工作副本填写handoff文件，不修改包原始清单以把未完成必交功能改成可选。确有外部环境限制，记录blocked和具体证据，不虚构功能支持。
