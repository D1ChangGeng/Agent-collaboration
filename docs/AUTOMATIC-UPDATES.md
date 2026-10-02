# Automatic upgrades

ACS v1.3.0 enables automatic upgrades by default for new installations.
It checks the latest stable Release daily on the installed Linux Runtime host
and activates eligible updates after verification. The installation's recorded
machine, owner account, home directory, Harness selection and web settings
determine the update target.

Existing v1.2.0 installations need one AI-guided upgrade using the verified
[v1.3.1 Release Bootstrap](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.3.1).
Ask the setup Skill to inspect the installation, verify the new Bootstrap and
Release digests, preview the upgrade and validate the connections afterward.
The v1.2.0 installation has no automatic update service to perform that first
upgrade.

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
4. Reads the existing provider configuration and checks service health and
   the owner's existing Grant authorization.
5. Refreshes owned local Skills transactionally and activates the verified
   version, retaining the previous version for rollback.

The update uses existing projects, SourceBindings, Grants and provider
composition. Project setup, new SourceBindings or Grants, and Compose changes
require their respective setup operations. Custom edits to managed files need
ownership review before an upgrade can proceed. Skills on separate client hosts
are refreshed through the setup Skill's client maintenance lifecycle.

## Connections after activation

The stable `<installation-root>/acs_launcher.py` entry resolves the active
version from `state.json` when a new MCP process starts. Configured local,
SSH, WSL and private Tunnel launch commands therefore follow the activated
version. Running MCP sessions continue on the version they started with; start
a new connection to use the activated version. A long-running Tunnel process
uses it when its MCP process next starts.

A failed verification leaves the active version available.
Inspect the update result and reconnect through the stable launcher to verify
`tools/list`, `read_profile` and `list_projects` after activation. Verify
`load_project` for registered projects and actual ChatGPT calls for enabled web
access.

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
