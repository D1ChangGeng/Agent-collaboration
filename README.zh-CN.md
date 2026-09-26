# agent-collaboration-setup

这是一个 **只负责设置（setup-only）** 的 Harness-agnostic Agent Skill，用于把 **ACHP（Agent Collaboration & Handoff Protocol）** 安装、接管、升级或修复到任何空白项目或进行中项目。

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
    └── runtime/
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

卸载默认保留项目自己的 `.agents/knowledge/` 和 coordination 数据。

如果确实需要全部清除：

```bash
python3 scripts/project_setup.py uninstall --root /path/to/repo --purge-data
```

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
└── runtime/
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

文件准备完成后：

```bash
git init
git add .
git commit -m "Initial release of Agent-collaboration v0.1.0"
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
- Runtime 协议必须 Harness-agnostic。
- Capability 按实际运行时验证，不能通过产品名猜测。
- Manual relay 是完全合法的标准模式。
- Harness Adapter 只能做增强，不能成为项目真相来源。
- Git 同步和消息 Relay 必须分离。
- `.agents/runtime/` 不保存为跨机器公共事实。
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
