# Agent Collaboration System v1.2.0

ACS v1.2.0 makes Runtime placement, client connections and project Source discovery explicit in AI-guided setup. Install the Runtime and connect selected clients, then initialize or adopt projects through the installed setup Skill.

## Highlights

- **Confirmed Runtime placement.** Choose local Linux, a named SSH target or a named WSL distribution. Installation previews observe the machine identity, account and home directory; apply checks that binding before installing.
- **Client setup on selected hosts.** Codex and OpenCode clients receive their Skills and MCP configuration on their own hosts. SSH/WSL setup returns a caller-side stdio descriptor. Machine installation supports an empty project list; project initialization follows when needed.
- **Explicit ChatGPT web choice.** Select `enable`, `skip` or `later`. Enabled setup generates the Runtime-host MCP/Tunnel plan, official documentation links, Agent execution steps and required owner account actions. Deferred setup records its resume entry.
- **Existing-project Source discovery.** Read-only local, authorized SSH and WSL probes identify the actual machine/account, Source path, repository, Project/Root identity, Git commit/tree and scoped working-tree state. The Agent compares relevant candidates before guarded Source registration.
- **Guides included in installed Skills.** The setup Skill carries getting-started, troubleshooting, web-connection, project-adoption and Source-discovery guides. Installation checks ownership of nested documentation directories and rejects linked payload paths.
- **Verified release delivery.** The Release includes a standalone Bootstrap, ZIP/TAR archives and `SHA256SUMS.txt`. Archive and embedded file-manifest verification retain exact commit/tree readback, versioned installation directories and the previous release for rollback.

## Install or upgrade

Give the [v1.2.0 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.2.0) to Codex or OpenCode and ask it to install or upgrade using the [standalone Bootstrap asset](https://github.com/D1ChangGeng/Agent-collaboration/releases/download/v1.2.0/acs_bootstrap.py) with `--version v1.2.0`. The Agent verifies the downloaded Bootstrap against `SHA256SUMS.txt`, previews changes and executes installation/configuration commands. You choose the Runtime/client destinations and complete required machine authorization and account confirmations.

Upgrades use the same verified flow with the existing Runtime destination, client hosts and web choice. The previous version remains available for rollback while the new installation is checked.

## Compatibility and connection verification

Runtime and filesystem Source/CAS services run on Linux. Windows Codex/OpenCode clients connect through SSH to a Linux host or through a named WSL distribution. Windows Source checkouts support read-only Git discovery; registration uses an explicitly admitted Linux provider view.

Client readiness requires service health and actual `tools/list`, `read_profile` and `list_projects` readback from each selected client. ChatGPT web readiness requires completed owner Platform/ChatGPT actions, observed Tunnel health and actual ChatGPT tool discovery and readback. The web profile serves one installation owner; follow the [official Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) for account permissions and workspace association.

See the [getting-started guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.2.0/docs/GETTING-STARTED.md), [Source-discovery guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.2.0/docs/runtime/SOURCE-DISCOVERY.md) and [private Tunnel runbook](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.2.0/docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md).

The project retains [Sustainable Use License 1.0](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.2.0/LICENSE).

## 简体中文

v1.2.0 完善 AI 引导安装：确认 Linux/SSH/WSL Runtime 位置与客户端，明确选择立即启用、跳过或稍后配置 ChatGPT 网页连接。Agent 执行安装与配置命令，用户完成必要授权和账户确认；连接状态以实际工具调用为准。现有项目先发现并核对真实 Source、项目身份及 Git 版本，再进行注册。保留发行包校验、版本化安装和回滚，Windows 客户端通过 SSH/WSL 连接。

[Full changelog](https://github.com/D1ChangGeng/Agent-collaboration/compare/v1.1.0...v1.2.0)
