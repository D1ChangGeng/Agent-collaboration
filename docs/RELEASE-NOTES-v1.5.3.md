# Agent Collaboration System v1.5.3

2026-10-14

ACS v1.5.3 completes the maintenance-lock handoff when migrating an existing
Windows/WSL owner login task to the stable background startup entry.

## Existing task migration

The Windows helper locates the selected installation's Linux recovery-lock
holder and verifies its owner account, reviewed previous entry or same-root
stable maintenance command, and process creation identity. It sends SIGTERM
to that holder and waits for exit before starting the replacement task.
Core, SSH and web processes retain their existing supervision. The saved task
definition supplies rollback.

Use `scripts/acs_windows_startup.ps1` from the verified
[v1.5.3 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.3).
For an existing task, retain its `-TaskName` and supply `-AdoptExisting` with
the reviewed `-LegacyEntrypoint`. Preview the confirmed machine/account binding,
then apply and check. See [getting started](GETTING-STARTED.md) and
[owner startup recovery](runtime/STARTUP-RECOVERY.md) for the complete procedure.

## Verification scope

The candidate helper completed adoption and apply against an existing production
owner task using the published v1.5.2 Core. The migrated task selected the stable
maintenance entry and was observed running in the background. This evidence
covers task migration and maintainer handoff; a full machine reboot with the
final configuration remains unmeasured.

Runtime code matches v1.5.2; its
[startup capabilities](RELEASE-NOTES-v1.5.2.md) remain available.
Distribution v1.5.3, setup Skill v0.4.0 and Runtime package v0.1.0 are
independently versioned. Distribution retains the
[Sustainable Use License 1.0](../LICENSE).
