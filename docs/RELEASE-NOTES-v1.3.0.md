# Agent Collaboration System v1.3.0

2026-10-03

ACS v1.3.0 adds automatic upgrades and a stable MCP launcher. New installations
enable daily checks of the latest stable Release, with automatic activation of
compatible updates within the installed major version. Updates reuse the
recorded machine, owner account, home directory, Harness selection and web
settings.

## Highlights

- **Automatic upgrade controls.** New installations enable updates by default.
  Normal upgrades preserve an existing disabled setting when neither
  `--auto-update` nor `--no-auto-update` is supplied. These installation flags
  explicitly enable updates or opt out.
- **Owner scheduling and connection catch-up.** ACS prefers a systemd user
  timer, falls back to the owner's crontab when available, and starts due
  background checks through new stable-launcher connections. Inspect the
  actual scheduler state: host sleep, user-manager availability after logout
  and the cron daemon affect execution.
- **Verified activation.** Updates require the supported compatibility
  contract and unchanged license, Runtime schema and migrations, provider
  composition and MCP tool catalog. ACS verifies archive SHA-256, file
  manifests and installed files, builds the new locked Python environment,
  then checks provider health and the owner's existing Grant authorization
  before activation.
- **Stable connections.** New local, SSH, WSL and private Tunnel MCP processes
  resolve the active Release through the installed launcher. Running sessions
  retain their starting version; reconnect to use the activated version.
  The web setup helper accepts `--installation-root` to generate a stable
  Tunnel plan for a matching verified installation.
- **Skills and recovery.** Owned local Skills refresh transactionally; Skills
  on separate client hosts follow their client maintenance workflow. The
  previous Release remains available for manual rollback. Rollback records
  the version being rolled back as `held_version`, requiring review before
  that version can be activated again.

## Install or upgrade

Give the [v1.3.0 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.3.0)
to Codex or OpenCode and ask the Agent to install or upgrade using its
[standalone Bootstrap](https://github.com/D1ChangGeng/Agent-collaboration/releases/download/v1.3.0/acs_bootstrap.py)
with `--version v1.3.0`. Verify that Bootstrap's SHA-256 against the Release's
`SHA256SUMS.txt` before executing it.

The Agent confirms local Linux, a named SSH target or a named WSL distribution,
observes the machine/account/home binding, and previews the installation before
apply. It configures the selected client hosts and records the explicit
ChatGPT web choice. The Agent executes commands; you complete required machine
authorization and owner account confirmations. Runtime and filesystem
Source/CAS services run on Linux; Windows clients connect through SSH or WSL.

An existing v1.2.0 installation needs this first AI-guided upgrade to v1.3.0
through the verified Release Bootstrap. Subsequent eligible upgrades use the
recorded installation settings.

Use the installed Bootstrap on the Runtime host as the recorded owner:

| Action | Bootstrap arguments |
| --- | --- |
| Inspect policy and scheduler | `--set-auto-update status` |
| Enable or disable upgrades | `--set-auto-update on` / `--set-auto-update off` |
| Check immediately | `--update --force-check` |
| Check and apply an eligible update | `--update --apply --force-check` |
| Restore the retained previous Release | `--rollback --apply` |

`--force-check` requests an immediate check while preserving the enabled policy
and compatibility checks.

## Verify the installation

Inspect the enabled policy, observed scheduler backend/state, last update result
and next check time. Verify service health and actual `tools/list`,
`read_profile` and `list_projects` calls through each selected client. For
registered projects, verify `load_project` against the intended project and
SourceBinding.

For enabled ChatGPT web access, complete the required owner Platform/ChatGPT
actions, verify Tunnel health, and observe actual ChatGPT tool discovery and
readback after connection or reconnection. Runtime, service and ChatGPT
readiness are measured for the installed host and client configuration.

See [getting started](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.0/docs/GETTING-STARTED.md),
[automatic upgrades](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.0/docs/AUTOMATIC-UPDATES.md),
the [private Tunnel runbook](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.0/docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md)
and [troubleshooting](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.0/docs/TROUBLESHOOTING.md).

The project retains [Sustainable Use License 1.0](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.3.0/LICENSE).
