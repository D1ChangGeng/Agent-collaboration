# Automatic upgrades

New ACS installations enable automatic upgrades by default.
It checks the latest stable Release daily on the installed Linux Runtime host
and activates eligible updates after verification. The installation's recorded
machine, owner account, home directory, Harness selection and web settings
determine the update target.

The v1.5 Runtime schema and MCP catalog transition requires a guided upgrade.
Use the verified
[v1.5.2 Release Bootstrap](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.2)
for an AI-guided upgrade. The Agent inspects the installation, verifies Bootstrap
and Release digests, executes the preview and upgrade commands, and validates
the actual access mode and connections afterward. See the
[release notes](RELEASE-NOTES-v1.5.2.md) and the transition below.

## Controls

Pass `--no-auto-update` to the Release Bootstrap during installation to opt out,
or `--auto-update` to enable it explicitly. A regular upgrade preserves an
existing disabled setting when neither flag is supplied.
For an existing installation, run its installed Bootstrap on the Runtime host
as the recorded owner. Use the same SSH target or WSL distribution when that is
where ACS runs. The installation report identifies the private installation
root and Bootstrap interpreter.

```bash
python3 <installation-root>/acs_bootstrap.py --set-auto-update status
python3 <installation-root>/acs_bootstrap.py --set-auto-update off
python3 <installation-root>/acs_bootstrap.py --set-auto-update on
```

Inspect status after changing the setting. Disabling stops scheduled checks and
connection catch-up; enabling registers the available owner scheduler and
enables connection catch-up.

Check the latest stable Release immediately, or check and apply an eligible
update:

```bash
python3 <installation-root>/acs_bootstrap.py --update --force-check
python3 <installation-root>/acs_bootstrap.py --update --apply --force-check
```

`--force-check` requests an immediate check while preserving the enabled policy and
compatibility requirements. The check command reports the candidate; `--apply`
requests activation after the required checks. These commands reuse the
existing installation binding and configuration.

## Scheduling and catch-up

The updater prefers a same-owner systemd user timer. When that user manager is
unavailable, it can register an owner crontab entry. New connections through the
stable MCP launcher also start a background catch-up check, so a waking host can
resume checking while the MCP connection starts. The policy normally checks
once per day; network or update errors become eligible for retry after an hour.

Read policy and scheduling state separately:

| Readback | Meaning |
| --- | --- |
| Enabled policy | ACS may check and apply eligible updates. |
| Active systemd user timer | The owner's user manager currently runs the timer. |
| Registered cron entry | The owner's update entry exists; cron execution depends on the host's daemon. |
| Inactive timer or unregistered cron entry | The scheduled path needs attention; enabled connection checks can still run when a new MCP process starts. |
| Connection checks | A new stable-launcher MCP connection can trigger a due background check. |
| Last result and next check | The last recorded attempt and the next eligible check time. |

A sleeping host cannot execute a check. A systemd user timer depends on its user
manager, which may stop after logout; a registered cron entry alone does not
prove the daemon is running. Connection catch-up works when a new MCP process
starts. Report the observed backend and state when confirming update readiness.

## Eligible updates

Automatic activation requires a published stable Release in the same major
version. The Release must declare the supported automatic update compatibility
contract, with identical `LICENSE`, Runtime schema and migration files, provider
composition and MCP tool catalog. A new major version or a changed contract
requires explicit review and an AI-guided upgrade.

Before activation, ACS:

1. Verifies the archive against `SHA256SUMS.txt`, safely extracts it and checks
   every packaged file against its manifest.
2. Verifies the previous installed Release files and the ownership of managed
   launcher, updater and local Skill files.
3. Builds a new version's Python environment from the dependency lockfile.
4. Reads the existing provider configuration and checks service health, trusted
   owner identity, active state and explicit revocation; shared mode checks its
   configured Grant authorization.
5. Refreshes owned local Skills transactionally and activates the verified
   version, retaining the previous version for rollback.

The update uses the existing projects, SourceBindings, selected access mode,
identity records, explicit revocation and provider composition. Project setup,
new SourceBindings and shared Grants, and Compose changes require their
respective setup operations. Custom edits to managed files need ownership review
before an upgrade can proceed. Skills on separate client hosts are refreshed
through the setup Skill's client maintenance lifecycle.

## Guided upgrade to v1.5.2

The Agent uses `--version v1.5.2` with the verified Release Bootstrap and the
recorded Runtime host, machine/account/home binding, client selection and web
choice. It executes installation and diagnostic commands, retaining the existing
configuration, credentials, cryptographic key references, projects, Root/Route
identities, SourceBindings, deduplication, recorded evidence and revocation state.

New private installations use `access_mode: owner`. During a guided upgrade, the
installer can adopt owner mode for a positively identified existing private Root
profile. The adoption verifies its credential, backs up the original
configuration as `.before-owner-upgrade`, and updates active, nonrevoked
registration records while preserving their identities. Explicit shared
configurations retain shared mode. Loading an unspecified configuration retains
shared behavior until explicit adoption. Read back `read_profile.access_mode`
after restart or reconnection.

Existing Receivers have a separate signed deployment binding. Owner/native
adoption preserves the original profile, Node identity and key references,
updates the Endpoint registration and matching process configuration together,
then restarts and reads back the committed revision/digest, actual native mode,
Session and readiness. Revoked and retired objects retain their lifecycle state.
The [owner migration contract](runtime/OWNER-RUNTIME.md#existing-installations-and-migration)
describes this transition. Retain the previous Release and configuration backups
for recovery; confirm both application and database compatibility before rollback
across a schema change.

## Connections after activation

The stable `<installation-root>/acs_launcher.py` entry resolves the active
version from `state.json` when a new MCP process starts. Configured local,
SSH, WSL and private Tunnel launch commands therefore follow the activated
version. Running MCP sessions continue on the version they started with; start
a new connection to use the activated version. A long-running Tunnel process
uses it when its MCP process next starts. For a catalog/schema upgrade, the Agent
restarts the configured Tunnel/MCP process, verifies Tunnel health, then guides
the owner to select **Refresh** on the existing connection in ChatGPT Plugins,
inspect refreshed tool metadata and start a new chat. The
[owner contract](runtime/OWNER-RUNTIME.md#chatgpt-connection-metadata) includes the
official metadata-refresh procedure.

A failed verification leaves the active version available.
Inspect the update result and reconnect Codex/OpenCode through the stable launcher.
Verify `tools/list`, the actual mode in `read_profile` and `list_projects`.
Owner verification also reads `filesystem_context` and a selected current path.
Verify `load_project` product and Management Root observations for registered
projects, and actual ChatGPT calls in a new chat for enabled web access.

## Startup recovery

Before executing the active MCP version, the stable launcher restores the
existing owner Core provider project from its private installation configuration.
It verifies owned files and Release composition and brings the recorded
PostgreSQL/Temporal services up. Normal Runtime authentication applies the
existing identity and revocation state.

For Windows/WSL installations, maintain the owner login task from the full
verified Release on the Windows client. Run `scripts/acs_windows_startup.ps1`
with the recorded distribution, Linux account, installation root and machine
identity: preview first, then `-Apply`, then `-Check`. Existing task migration
backs up its definition and receipt. The GUI host launches WSL in the background,
and the task calls the stable launcher's `--maintain-startup` entry.
New maintenance processes verify and select the active Release helper.
After activation, restart the registered task and verify the selected version
and actual service/connection health. The
[startup recovery guide](runtime/STARTUP-RECOVERY.md) includes commands and
reviewed adoption of existing tasks.

Core, private SSH and Secure MCP Tunnel recovery have independent attempts and
health observations. A `provider_backend_repair_required` result directs the
Agent to `scripts/acs_docker_backend.py --provider-config <private-provider-config>`.
A readable existing provider returns `ready`; otherwise the helper inspects
the actual Docker data root and preserved containerd store before presenting a
repair plan. Applying a plan requires its current digest, explicit authorization
for shared Docker/containerd changes, OS administration and a new private
backup directory. Record the repair and rollback result separately from
ordinary startup.

Use `acs_launcher.py --installation-root <installation-root> --check-startup`,
task readback and service diagnostics to establish observed startup state.
The Agent verifies each selected client's actual MCP calls afterward.

## Rollback and recovery

Run a manual rollback through the installed Bootstrap on the same Runtime host
and owner account:

```bash
python3 <installation-root>/acs_bootstrap.py --rollback --apply
```

ACS verifies and reactivates the retained previous Release and restores owned
local Skills. New connections follow that version. Rollback records the
rejected version as `held_version`; automatic checks require explicit review
before applying that same version again. A newer compatible stable Release can
still become eligible.

For a failed check, inspect status and service diagnostics, resolve the reported
cause and retry with `--update --apply --force-check`. For ownership or
compatibility review, ask the setup Skill to inspect the installation and
preview the guided upgrade. See [troubleshooting](TROUBLESHOOTING.md).
