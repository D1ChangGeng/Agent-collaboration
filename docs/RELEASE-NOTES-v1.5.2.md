# Agent Collaboration System v1.5.2

2026-10-14

ACS v1.5.2 improves owner machine startup recovery for Windows/WSL installations
and adds a reviewed Docker/containerd backend repair workflow.

## Windows background recovery

A Windows owner login task uses a GUI background host to run WSL maintenance
and propagate the process exit code to Task Scheduler. The stable launcher
verifies the active Release helper before running `--maintain-startup`.

`scripts/acs_windows_startup.ps1` provides preview, `-Apply` and `-Check`
modes bound to the selected distribution, Linux account, installation root and
machine identity. Bootstrap's `client_connection.background_startup` object
provides the script source, parameters and preview/apply/check sequence.
The helper targets Windows x64 and uses the installed 64-bit .NET Framework
C# compiler. New tasks use an owner login trigger, a single instance and
failure retry. Existing task adoption checks its action/owner and saves the
task definition and receipt before migration.

## Existing provider recovery

Core startup distinguishes `provider_backend_repair_required` while configured
Core, SSH and web recovery continue as independent attempts.
`scripts/acs_docker_backend.py` reads the daemon's actual data root and
containerd connection. A readable provider returns `ready`; a backend repair
plan checks preserved metadata, snapshots and ACS container labels.

Applying a plan requires its current digest, explicit authorization for shared
Docker/containerd changes, OS administration and a new private backup directory.
The helper records the plan and service-unit backup, retains container data in
place, validates the provider readback and rolls back the generated
configuration if validation fails. Existing configuration or running workloads
require plan review.

## Install or upgrade

Use the verified
[v1.5.2 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.2).
Verify `acs_bootstrap.py` against `SHA256SUMS.txt`, preview the confirmed
Runtime host/account/home binding, and apply with the Agent. For Windows/WSL,
complete task preview, apply and check on the Windows client from the full
Release. Read back services and each selected client's actual MCP connection.
See [getting started](GETTING-STARTED.md),
[automatic upgrades](AUTOMATIC-UPDATES.md) and
[owner startup recovery](runtime/STARTUP-RECOVERY.md) for commands and migration.

## Verification scope

The standard Windows helper also completed preview/apply/check on an isolated
Scheduled Task bound to a real WSL distribution. Its GUI host and WSL ran in
the background; repeated apply retained the same process and one backup.
This fixture validates the task installation mechanism. The standard Docker
helper read both existing ACS provider containers from the current backend and
returned `ready` with `changes: []`.

Observed recovery includes a restarted Windows task running in the background,
restored existing PostgreSQL and Temporal services, and SSH/Tunnel retry with
HTTP 200 health readback. Windows Codex and OpenCode each discovered 48 tools
and reported owner access through their real MCP configurations. Web validation
read current project context and remote files.

This evidence covers the measured task, service and connection recovery path
on the tested configuration. A full machine reboot with the final configuration
remains unmeasured.

Distribution v1.5.2, setup Skill v0.4.0 and Runtime package v0.1.0 are
independently versioned. Distribution retains the
[Sustainable Use License 1.0](../LICENSE).
