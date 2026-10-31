# Owner startup and transport recovery

The selected Codex/OpenCode MCP command owns stdio startup. A stable
`acs_launcher.py --installation-root <installation-root>` resolves the
owner/machine-bound active Release, then restores configured dependencies before
executing its MCP entry. SSH and WSL client descriptors enter the selected
Runtime host first.

## Core dependencies

Recovery verifies the recorded private provider identity and the active
Release's Compose digest. It starts that owner Compose project with bounded
readiness (`--wait`), preserving PostgreSQL data, credentials, Project/Root
identities and configured authorization. Normal Runtime authentication still
follows. Startup uses the existing schema and active authorization records.
New service containers use `restart: unless-stopped`. Existing containers
receive that policy after their project/service ownership is read back.

Docker daemon availability is a machine prerequisite. Inspect the actual init
manager and installed Docker service before choosing its startup command.
On WSL with Docker's systemd units, configure `[boot] systemd=true` and enable
`docker.service` and `containerd.service`. Preserve and back up existing
distribution settings. A boot command using `service docker start` requires
an installed SysV init script and a successful real invocation. Configuration
applies at the next distribution cold start. Record whether service recovery
or distribution/machine restart was actually measured.

## Docker and containerd backend diagnosis

An available Docker daemon can still be connected to a containerd store that
does not expose the preserved ACS provider containers. Core recovery reports
`provider_backend_repair_required` for this condition. Core, SSH and web
recovery remain independent attempts.

Run diagnosis on the recorded Runtime host with the verified active Release
helper and the private provider configuration:

~~~bash
python3 <active-release>/scripts/acs_docker_backend.py \
  --provider-config <private-provider-config>
~~~

The helper reads Docker's actual data root, containerd address, storage driver
and server version. A readable existing provider returns `state: ready` and an
empty change list. If backend repair is needed, it inspects the preserved
`<data-root>/containerd/daemon` metadata and snapshot directories and the
existing ACS container labels before offering a plan. Check the daemon context
and service units as part of review:

~~~bash
docker info --format '{{json .}}'
docker context inspect
systemctl cat docker containerd
~~~

Docker's `data-root` and connection to standalone containerd are documented in
the [official daemon reference](https://docs.docker.com/reference/cli/dockerd/).
Use the observed paths in the plan. An existing containerd configuration,
running containerd tasks, a remote daemon or a different containerd address
returns `review_required`; review the stated reasons and generate a new plan
after resolving them.

Docker and containerd are shared machine services. Present the exact plan and
obtain explicit authorization for its configuration changes and service
restarts. Apply requires OS administration, the current plan digest and a new
absolute private backup directory:

~~~bash
sudo python3 <active-release>/scripts/acs_docker_backend.py \
  --provider-config <private-provider-config> \
  --apply --shared-runtime-confirmed \
  --plan-digest <reviewed-plan-digest> \
  --backup <new-absolute-backup-directory>
~~~

Apply rechecks the plan, records it and backs up service-unit definitions before
writing the reviewed containerd connection configuration and restarting
services. Existing container data stays in its original location. The offered
automatic plan requires an absent containerd configuration; if validation fails
after the generated configuration is written, recovery removes that configuration
and restarts the prior services. Existing configurations require a reviewed
merge before this path can proceed.

Read back the original provider containers, PostgreSQL/Temporal health,
`--check-startup` component results and actual client MCP calls after repair.

## Windows owner login task for WSL

For a Windows client using a selected WSL Runtime, run
[scripts/acs_windows_startup.ps1](../../scripts/acs_windows_startup.ps1) from a
full verified Release or its verified installed setup Skill payload on the
Windows client under the installing Windows account.

The supplied helper targets Windows x64. Before apply, check WSL, the Task
Scheduler PowerShell cmdlets and the installed 64-bit .NET Framework C# compiler
at `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`.
The helper compiles its host as an x64 GUI executable.

Use Bootstrap's `client_connection.background_startup` object for the script
source, confirmed parameter binding and preview/apply/check sequence. It
identifies the distribution, observed Linux owner account, installation root
and full machine identity. The default invocation previews the machine-bound
task:

~~~powershell
.\scripts\acs_windows_startup.ps1 `
  -WslDistribution '<confirmed-distribution>' `
  -RuntimeUser '<observed-linux-owner>' `
  -LinuxInstallationRoot '<private-installation-root>' `
  -ExpectedMachineId '<observed-full-machine-id>'
~~~

Run the same command with `-Apply` to register or migrate the task, then
`-Check` to inspect its startup state. Both modes recheck the selected Runtime
binding. An installation with `startup.enabled=false` returns `owner_disabled`.
Keep the receipt and backup references in private installation storage.

The task action uses the GUI-subsystem
[background host](../../assets/windows/acs_background_host.cs), which launches
the system WSL executable with `UseShellExecute=false` and
`CreateNoWindow=true`, waits for the process and propagates its exit code to
Task Scheduler. The task calls:

~~~text
/usr/bin/python3 <installation-root>/acs_launcher.py --installation-root <installation-root> --maintain-startup
~~~

The stable launcher verifies the active Release recovery helper before
maintenance starts. The helper holds an owner lock, re-reads selected state and
retries recovery every 30 seconds. New tasks use the installing Windows owner's
interactive principal, login trigger, a single instance, unlimited running
duration and failure retry. This keeps recovery active before a Harness opens
an MCP connection. Disable automatic recovery through the owner startup setting.

For a verified existing task, supply its `-TaskName` and `-AdoptExisting`
with the reviewed `-LegacyEntrypoint`. Adoption checks the current task action
and owner. Migration backs up the task definition and existing receipt,
preserves its trigger and settings, then selects the GUI host and stable
maintenance entry. A task whose binding needs review remains a separate
maintenance decision.

### Maintenance lock handoff during migration

When migrating an existing task, the helper hands off the selected
installation's Linux `login-recovery.lock` before starting the replacement
action. It locates the lock through the installation's private Runtime
configuration and reads its holder from the kernel lock table.

The helper verifies the holder's Linux owner account, the reviewed
`-LegacyEntrypoint` or the same installation's stable
`acs_launcher.py --maintain-startup` command, and process creation identity.
It sends SIGTERM to that verified holder and waits for exit. A holder whose
identity needs review stops migration for owner review; the saved task
definition supplies rollback. Core, SSH and web processes retain their
existing supervision.

After applying or restarting the task, read back its principal/action, running
state and actual selected Runtime version. A long-running task is the expected
maintenance state. Check Docker, PostgreSQL/Temporal, configured SSH/Tunnel
health and actual MCP authorization separately. Record an observed task restart
as task recovery evidence; machine reboot evidence requires its own measured run.
The [Microsoft process reference](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.createnowindow)
describes the process creation option.

## Transport supervision

Private SSH deployment records an owner-private profile containing its
allowlisted SSH target, private root/control socket and exact loopback port
forwards. Launch uses a per-profile gate and one supervisor lock. An existing
master is adopted after process owner, control socket, configured target and
forwarding arguments match. SSH uses noninteractive authentication, connection
bounds and server-alive detection. A failed master reconnects under monotonic
bounded exponential backoff, capped at 30 seconds. Multiple Harness starts
share the same supervisor. Host identity and credential checks govern recovery.

Secure MCP Tunnel has a separate owner-private startup profile referencing the
reviewed executable and digest, existing private Tunnel profile, PID and health
marker locations. Recovery validates the process executable, owner and profile
before adopting it. A dead client restarts with loopback admin/health endpoints.
Existing profile credentials stay in their original protected storage. The
Tunnel client's polling handles network reconnection while its process is alive;
supervision covers process exit. Read `/healthz` and `/readyz` to distinguish
process health from remote readiness. Expired/revoked credentials require owner
repair.

Local MCP startup requests web supervision independently of web readiness.
Local collaboration can remain available during a web outage, including when
the Tunnel itself launches ACS stdio.

## Configuration and maintenance

Bootstrap state preserves `startup.enabled` (default true), optional
`startup.ssh_profile_ref` and `startup.web_profile_ref` across activation.
The references point to private validated JSON profiles managed by the setup
Agent. Schema names are `acs-private-ssh-startup/1` and
`acs-secure-tunnel-startup/1`; the implementation in
[scripts/acs_startup.py](../../scripts/acs_startup.py) defines their exact fields.
Run the stable launcher with `--check-startup` for component readback.
Ordinary stdio startup reserves stdout for MCP.

Newly configured clients receive a 120-second ACS initialization budget
(`startup_timeout_sec=120` for Codex, local MCP `timeout=120000` for OpenCode
tool discovery). Preserve larger owner settings. Task/caller waits retain their
own selected conditions and timeout settings. Existing clients receive the
reviewed connection-budget maintenance through setup.

A released version must contain the recovery helper in its manifest. Older
versions retain their installed compatibility selection and use guided
maintenance to obtain recovery. An owner-maintained private integration entry
can invoke the same reviewed helper while preserving immutable Release files
and installed Runtime/overlay compatibility pins. Record its helper digest and
back up the former entry and state first.

## Verification scope

Check missing and exited SSH masters, concurrent launches, restart/reconnect,
authentication failures, changed paths/binaries and Core service readiness.
Use isolated test profiles and ports for fault injection and preserve production
sessions. Read actual MCP discovery and `read_profile` through each configured
entry. Keep host, Release and channel evidence with the run that measured it.

The v1.5.2 Windows helper completed preview/apply/check on an isolated
Scheduled Task bound to a real WSL distribution. Its GUI host and WSL ran in
the background; repeated apply retained the same process and one backup.
This fixture validates the task installation mechanism. The standard Docker
helper read both existing ACS provider containers from the current backend and
returned `ready` with `changes: []`.

The v1.5.3 candidate helper completed `-AdoptExisting` and `-Apply` against an
existing production owner task using the published v1.5.2 Core. The migrated
task selected the stable maintenance entry and was observed running in the
background. This run measures task migration and maintainer handoff.

The owner recovery exercise observed the Windows task running after restart,
background host and WSL window handles at zero, restored existing
PostgreSQL/Temporal health, SSH/Tunnel retry with HTTP 200 readback, and owner
MCP connections in Windows Codex and OpenCode with 48 tools each. Web validation
read current project context and remote files. This evidence covers task and
service recovery on the tested configuration. A full machine reboot with the
final configuration remains unmeasured.

Official references:
[WSL boot settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config),
[Microsoft process creation](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.createnowindow),
[Docker daemon configuration](https://docs.docker.com/reference/cli/dockerd/),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
