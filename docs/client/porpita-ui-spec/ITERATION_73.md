# 第 73 轮 · 实机接管独立 SSH 项目

独立 SSH 项目已有登记与既存工作树时，保留原复核对象。用户从工作区确认打开 SSH 设置，在原 SSH 目标行连接主机。接管沿用 Porpita 的服务器部署、项目迁移以及主机身份校验。

接管后由新登记的所属 Runtime 服务提供原项目。原项目 ID、仓库路径和既存工作树可追踪，客户端按归属展示一条工作区。连接和接管过程使用可见状态提示，完成以原项目实际出现在所属服务为准。

连接、部署和迁移反馈留在对应主机卡片。连接或部署失败时原工作区仍可定位，同一张卡片允许重试，已有普通 SSH 终端恢复入口继续可用。完成回到工作台，原工作区可执行由新服务处理的 Git 操作。

对应 M.02.32。使用接管前已存在的真实 Linux 仓库与工作树，Windows 隔离档案加载原独立 SSH 登记。 [复核入口](ITERATION_70.md) · [接管回放](tools/observe-physical-porpita.cjs)

实机保留原工作区，进入 Linux SSH 主机卡片后完成连接与接管。托管服务读到原项目 ID 和路径，后续操作使用原工作树。正在运行的终端和其他语言继续按各自条件验收。 [接管前](evidence/iteration-72-74-physical-en/i73-standalone-project-before-adoption.png) · [接管后](evidence/iteration-72-74-physical-en/i73-adopted-server.png)
