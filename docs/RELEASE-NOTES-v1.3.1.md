# Agent Collaboration System v1.3.1

2026-10-03

ACS v1.3.1 clarifies ChatGPT web setup through the installation owner's existing
external browser on their client machine. Platform and ChatGPT account
pages use that browser; Tunnel CLI configuration and services run on the
confirmed Runtime host.

## ChatGPT web setup

For browser opening and navigation, the Agent verifies working OS or
external browser control in the current Harness and acts within the owner's
setup authorization. It requests additional authority when the intended
operation requires it. Browser control capability is specific to that Harness
and client environment. The owner completes required login, permissions,
secret entry and connection consent.

The Agent searches and fetches current official documentation read-only,
independently of account actions. When browser control is unavailable
or the owner chooses guided setup, the Agent provides official links, exact
pages, current labels, required actions and expected results. It awaits the
owner's completion, then verifies the actual MCP connection and tool results.

On the confirmed Runtime host, the Agent installs and configures the Tunnel
client, checks local MCP access and Tunnel health, and verifies service
persistence. After owner account confirmations, it checks actual ChatGPT tool
discovery and readback. The
[private Tunnel runbook](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md)
provides the connection steps and recovery guidance.

## Install or upgrade

Give the
[v1.3.1 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.3.1)
to Codex or OpenCode and ask the Agent to install or upgrade with its
[standalone Bootstrap](https://github.com/D1ChangGeng/Agent-collaboration/releases/download/v1.3.1/acs_bootstrap.py)
and `--version v1.3.1`. Verify the Bootstrap's SHA-256 against the Release's
[SHA256SUMS.txt](https://github.com/D1ChangGeng/Agent-collaboration/releases/download/v1.3.1/SHA256SUMS.txt)
before executing it.

The Agent confirms local Linux, a named SSH target or a named WSL distribution,
observes the machine, owner account and home directory, and previews the
installation before apply. For an existing installation, it reuses the recorded
host binding, client Harness selection and ChatGPT web choice. The owner
completes required machine authorization and account confirmations.

Existing v1.3 installations with automatic upgrades enabled can receive this
compatible patch through their recorded update policy. Existing v1.2
installations need a first guided upgrade using the verified v1.3.1 Bootstrap.

New installations enable automatic upgrades by default; upgrades preserve the
recorded policy. The v1.3 policy continues with daily stable Release checks,
scheduling on the owner account, connection catch-up and verified activation
within the installed major version. Activation checks the license, Runtime
schema and migrations, provider composition and MCP tool catalog. New MCP
connections through the stable launcher select the active Release; running
sessions retain their starting version. See
[automatic upgrades](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/docs/AUTOMATIC-UPDATES.md)
for policy controls and rollback.

## Verify the installation

Verify service health and actual `tools/list`, `read_profile` and `list_projects`
through each selected client. An empty project list is a valid initial result.
For registered projects, call `load_project` for the intended project and verify
its context and SourceBinding. For enabled ChatGPT web access, verify Tunnel
health and actual ChatGPT tool discovery and readback after owner confirmations
and connection or reconnection.

See
[getting started](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/docs/GETTING-STARTED.md),
the [operating guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/references/OPERATING-GUIDE.md)
and [troubleshooting](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/docs/TROUBLESHOOTING.md).

The project retains
[Sustainable Use License 1.0](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.1/LICENSE).
