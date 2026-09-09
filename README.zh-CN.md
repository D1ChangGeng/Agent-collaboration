# agent-collaboration-setup

这是一个 **只负责设置（setup-only）** 的 Harness-agnostic Agent Skill，用于把 **ACHP（Agent Collaboration & Handoff Protocol）** 安装、接管、升级或修复到源码仓库或长期存在的 Project Collaboration Workspace。

它最重要的边界是：

> **完成设置以后，这个 Skill 退出运行链路。**

后续正常协作只依赖：

```text
AGENTS.md
.agents/
```

不会要求模型为了正常开发再次主动加载这个 Skill。

## 为什么这样设计

不同 Harness 的跨会话能力并不一致，而且能力还会受到版本、权限、部署方式和运行环境影响。

因此 ACHP 不通过 `Codex / Claude Code / OpenCode` 这样的产品名称推断能力，而是在当前协作拓扑真正需要时，再判断对应能力是否已经被验证。

默认逻辑：

```text
单会话
  -> 不需要消息 Relay

多会话 + 同机器
  -> 只判断 same-host send

多会话 + 多机器
  -> 判断 cross-host send

能力 verified + 目标可寻址
  -> 可以自动 Relay

能力 unknown / unavailable
  -> 用户手动复制转发
```

**用户手动转发是正式支持的一等 Transport，不是异常兜底。**

与此同时：

> **消息同步与 Git 仓库同步相互独立。**

即使消息已经自动发送，接收方也不能假定代码已经 Pull。

## Skill 与协作机制本体的边界

```text
agent-collaboration-setup
        │
        │ 只负责 bootstrap / adopt / upgrade / repair
        ▼
目标项目
├── AGENTS.md                 <- 后续协作的统一入口
├── CLAUDE.md                 <- Claude Code 的极薄兼容路由
└── .agents/
    ├── protocol/
    ├── coordination/
    ├── knowledge/
    └── （Harness/Session context） # 本地运行上下文，不是安装目录
```

正常开发期间：

- 架构/目标推进；
- 工程实现；
- Review；
- Agent Handoff；
- Push / Pull；
- Session Relay；
- Knowledge 维护；

都不应该再次依赖本 Skill。

只有当你明确需要“设置或修改协作机制本身”时，才重新调用它。

## 推荐安装方式：一份源码，多 Harness 共用

先把仓库 clone 到一个稳定目录：

```bash
git clone https://github.com/D1ChangGeng/Agent-collaboration.git ~/.local/share/agent-collaboration-setup
cd ~/.local/share/agent-collaboration-setup
```

然后：

```bash
python3 scripts/install_skill.py --harness all
```

推荐的个人级路径：

| Harness | Skill 路径 |
|---|---|
| Codex | `~/.agents/skills/agent-collaboration-setup/` |
| OpenCode | `~/.agents/skills/agent-collaboration-setup/` |
| Claude Code | `~/.claude/skills/agent-collaboration-setup/` |

Codex 和 OpenCode 可以直接共享 `~/.agents/skills/`。

安装器默认优先建立指向同一份 Git checkout 的符号链接，因此以后只需要 `git pull` 一次。

如果系统不允许创建符号链接（部分 Windows 环境常见），安装器会自动退化为 copy 模式。

检查：

```bash
python3 scripts/install_skill.py --harness all --check
```

## 使用方式

### Agent 的使用决策模型

如果用户没有直接使用 `bootstrap`、`adopt`、`repair`、`upgrade` 或
`validate` 这些内部命令名，应先阅读
[Agent 使用与决策指南](references/OPERATING-GUIDE.md)。该指南规定 Agent
应先观察什么、哪些事实可以安全推导、什么时候才需要提问，以及如何把
用户表达映射为 Root / Route 生命周期操作。语义判断由 Agent 完成，脚本
只负责确定性的文件操作和客观验证。

需要精确查看能力边界时，阅读
[能力矩阵](references/CAPABILITY-MATRIX.md)；需要检查代表性用户旅程和回归
场景时，阅读[场景矩阵](references/SCENARIO-MATRIX.md)。矩阵中的
`supported`、`partial`、`unverified`、`architecture-allowed` 和
`unsupported` 不可相互替换。

推荐顺序是：

```text
用户意图
  → 检查精确目标路径和已有协作文件
  → 分类 Root / Route 当前状态
  → 只做安全推导
  → 只询问会改变下一步行为的未知事实
  → 先 dry-run 预览
  → 执行并回读
  → 验证结果不变量
```

不要因为 Session、工程师窗口、机器或 Execution Endpoint 发生变化就创建
新的 Route。Session attach、Endpoint 替换、SSH 源码访问、direct relay 和
协作配置迁移目前不是本 Skill 已实现并验证的运行时操作；应保留原有身份，
如实报告 `unverified` 或 `unsupported` 边界。

### 空白项目

对 Agent 说：

```text
使用 agent-collaboration-setup 在当前仓库 bootstrap ACHP。
```

### 已有项目

```text
使用 agent-collaboration-setup 将当前仓库 adopt 到 ACHP。
保留现有 AGENTS.md、CLAUDE.md、项目文档、代码和 Git 历史。
```

### 升级

```text
使用 agent-collaboration-setup 升级当前仓库的 ACHP 设置。
不要覆盖项目自己的 knowledge、task、handoff 和 project profile。
```

### 验证

```text
使用 agent-collaboration-setup 验证当前项目的 ACHP 设置。
```

不同 Harness 的显式调用语法可以不同，但以上自然语言意图是可移植的。

以上示例表达的是 setup 意图，并不表示 Python CLI 会解析任意自然语言。
遇到含糊请求时，Agent 应先依据使用指南检查目标，再决定是否提问，不应先
询问内部 schema 字段或凭 Harness 名称猜测拓扑能力。

## Project Collaboration Workspace 与 Route

Workspace 是长期项目协作、架构管理、目标推进和状态理解的管理根。它可以与真实源码仓库、执行 Session 和执行 Host 分离，也允许本身不是 Git 仓库。

```bash
python3 scripts/project_setup.py workspace adopt --root /path/to/workspace --dry-run
python3 scripts/project_setup.py workspace adopt --root /path/to/workspace
python3 scripts/project_setup.py workspace validate --root /path/to/workspace
python3 scripts/project_setup.py route list --workspace /path/to/workspace
```

如果 Workspace 中存在尚未登记、但看起来像 Route 的目录，应先只读查看候选。
候选不会因为被发现就自动写入 registry；只有用户明确选择后，才使用可重复的
`--include-route` 纳入登记：

```bash
python3 scripts/project_setup.py workspace adopt \
  --root /path/to/workspace --list-candidates
python3 scripts/project_setup.py workspace adopt \
  --root /path/to/workspace --include-route "C Route" --dry-run
```

新增 Route 时不复制 A/B 或其他路线：

```bash
python3 scripts/project_setup.py route create \
  --workspace /path/to/workspace \
  --path "C Route" \
  --route-id c-route \
  --display-name "C Route"
```

已有 Route 的 adopt 应在该 Route 自己的独立迁移阶段执行。工具会保留已有 `AGENTS.md`、`.agents/knowledge/`、架构资料和状态：

```bash
python3 scripts/project_setup.py route adopt \
  --workspace /path/to/workspace \
  --path "Existing Route"
```

Root registry 只保存 Route 的 canonical 四字段：ID、path、display name 和 lifecycle status。当前 Session 进度留在 Harness context。只有当已经核验的 Source Repository 事实确实需要跨 Session 保留时，Route 才按需创建可选的 `.agents/state/source-state.yaml`；Route 初始化不再创建全为 `unknown` 的空记录。不能从历史路径或 Harness 名称推断当前 baseline。

### Workspace schema 0.3 当前操作边界

Workspace 的 `bootstrap`、`adopt`、`upgrade`、`repair`、`validate` 按用户提供的精确路径运行。`workspace uninstall` 当前处于安全保护状态：在形成经过审阅的 ownership plan 之前会直接拒绝，并且不会修改文件。读取器继续兼容 schema 0.2；新写入只保留最小稳定结构：Root manifest 中的身份与 registry 位置、Root registry 中的 Route 身份与生命周期、Route metadata 中的身份与显式 Root contract 指针。旧版派生字段只读兼容，不再继续写入。

`route upgrade` 是显式 metadata 迁移边界，会同时规范 Route metadata 和 Root registry，并保留未识别的扩展字段。`route set-state` 与 `route rename` 只更新 Root registry，不在 `route.yaml` 中制造第二份生命周期真相。拆分/合并、移动路径式重命名、Endpoint 替换、restore 和 rollback 仍属于未来迁移契约，必须有明确证据、审阅和可恢复方案后才能实现。

Schema 0.2 数据仍可读取、验证或执行幂等 no-op；如果旧 registry 需要新增 Route，工具会先拒绝写入并要求显式完成 Workspace upgrade，避免旧 registry 中混入新版 Route 条目结构。

安装器 ownership hash 和 preflight 检查记录 setup 完整性。Live execution
continuity 由 Harness/session context 负责；source identity 由 Git 或 Route
Source State 负责；durable knowledge 由 self-evolution 负责。setup Skill
负责配置这些边界，不承担 Session execution recovery。

## 直接使用安装工具

Skill 内置一个只使用 Python 标准库的确定性安装器：

```bash
python3 scripts/project_setup.py adopt --root /path/to/repo
```

支持：

```text
bootstrap
adopt
upgrade
repair
validate
uninstall
```

强烈建议先预览：

```bash
python3 scripts/project_setup.py adopt --root /path/to/repo --dry-run
```

安装后：

```bash
python3 scripts/project_setup.py validate --root /path/to/repo
```

源码仓库的卸载默认保留项目自己的 `.agents/knowledge/` 和 coordination 数据。Workspace 的 uninstall 是独立的安全保护路径，目前会拒绝执行且不产生文件变更。

如果确实需要清除源码仓库中的全部 ACHP 数据：

```bash
python3 scripts/project_setup.py uninstall --root /path/to/repo --purge-data
```

已有内容的源码仓库应使用 `adopt` 并先审阅 dry-run；`bootstrap` 只用于真正
新的或空的仓库。`repair` 只补回能够证明属于 setup-managed 且缺失的组件；
如果内容发生漂移或 ownership 有冲突，应停止并交由 Review。只有显式的
`upgrade` 才负责刷新 setup-managed 协议内容。

## 项目中最终安装的内容

```text
AGENTS.md
CLAUDE.md
.agents/
├── README.md
├── config.yaml
├── manifest.json
├── protocol/
│   ├── CAPABILITIES.md
│   ├── RELAY.md
│   ├── GIT-SYNC.md
│   └── KNOWLEDGE.md
├── coordination/
│   ├── PROJECT.md
│   ├── roles/
│   ├── tasks/
│   ├── handoffs/
│   └── templates/
├── knowledge/
│   ├── README.md
│   ├── guides/
│   ├── decisions/
│   ├── observations/
│   └── archive/
└── （Harness/Session context） # 本地运行上下文，不由安装器创建
```

安装器不会粗暴覆盖原来的 `AGENTS.md`、`CLAUDE.md` 或 `.gitignore`，而是维护带边界标记的 managed block。

## Claude Code 兼容

Codex 和 OpenCode 可以直接读取 `AGENTS.md`。

Claude Code 的项目持久入口是 `CLAUDE.md`，因此安装器只增加一个很薄的兼容路由：

```text
@AGENTS.md
```

这样协作协议仍然只有一个权威入口，不需要复制两套正文。

## Knowledge

长期共享知识统一放在：

```text
.agents/knowledge/
```

推荐：

```text
guides/
decisions/
observations/
archive/
```

只保存真正会改变未来行动、且重新发现成本较高的知识。

这一层与 `self-evolution` 类型的知识生命周期设计兼容，但 ACHP 不依赖任何特定 Skill 或 Harness。

### `AGENTS.md` 的演进边界

`AGENTS.md` 是无条件常驻的基础认知层，只承载稳定身份、协作拓扑、
ownership / evidence 边界、跨会话连续性以及反复出现且代价高的基础纠偏。
只有当真实工作证明一项认知在未来 Session / Route 中稳定有效、启动时必须
出现，并且不能可靠地依靠按需检索知识恢复时，才考虑提升到这里。当前状态、
实现细节、设计理由、任务进展、工程师报告和临时证据应留在对应的 Route、
状态、知识或源码权威位置。

`self-evolution` 负责知识的发现、捕获、检索、修正、验证和维护；ACHP 不在
`AGENTS.md` 中复制第二套知识生命周期，也不让它退化为工作日志或第二份真相。

## 更新 Skill

推荐的 symlink 模式：

```bash
cd ~/.local/share/agent-collaboration-setup
git pull
python3 scripts/install_skill.py --harness all --check
```

如果使用 copy 模式：

```bash
git pull
python3 scripts/install_skill.py --harness all --mode copy
```

更新 Skill **不会偷偷升级现有项目**。

需要升级项目时明确执行：

```bash
python3 scripts/project_setup.py upgrade --root /path/to/project
```

这样协议升级始终可以被 Review。

## 创建你自己的 GitHub 仓库

文件准备完成后，先检查完整变更，只暂存准备公开的文件：

```bash
git init
git status --short
git add <准备提交的文件>
git diff --cached --check
git commit -m "Add Project Collaboration Workspace and Route support"
git branch -M main
git remote add origin git@github.com:D1ChangGeng/Agent-collaboration.git
git push -u origin main
```

公开源码仓库是 `D1ChangGeng/Agent-collaboration`；可安装 Skill 的 slug
以及本地 discovery 目录仍然是 `agent-collaboration-setup`。

## 开发与验证

```bash
python3 scripts/validate_skill.py
python3 -m unittest discover -s tests -v
```

仓库已经包含 GitHub Actions，在 push / pull request 时执行相同检查。

## 设计原则

- Skill 只负责设置，不承担运行时职责。
- 协作协议必须 Harness-agnostic。
- Capability 按实际运行时验证，不能通过产品名猜测。
- Manual relay 是完全合法的标准模式。
- Harness Adapter 只能做增强，不能成为项目真相来源。
- Git 同步和消息 Relay 必须分离。
- Harness/Session 能力观察保留在当前运行上下文，不写入跨机器公共项目事实。
- `.agents/knowledge/` 只保存高价值长期知识。
- 对已有项目优先复用权威文档，而不是复制。
- 协议升级必须显式执行、可审查、可回滚。

## 参考

- Agent Skills: https://agentskills.io/
- Codex Skills: https://developers.openai.com/codex/build-skills
- Codex AGENTS.md: https://developers.openai.com/codex/agent-configuration/agents-md
- Claude Code Skills: https://code.claude.com/docs/en/skills
- Claude Code Memory / AGENTS.md compatibility: https://code.claude.com/docs/en/memory
- OpenCode Skills: https://opencode.ai/docs/skills/
- OpenCode Instructions: https://opencode.ai/v2/docs/instructions
- self-evolution: https://github.com/D1ChangGeng/self-evolution

## License

当前默认使用 MIT License。正式发布前如果你希望更换许可证，可以直接替换 `LICENSE`。
