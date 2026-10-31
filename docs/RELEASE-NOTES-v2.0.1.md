# ACS v2.0.1

This patch repairs Windows owner startup recovery for an existing WSL Runtime.
It retains the communication schema and data transition introduced in
[v2.0.0](RELEASE-NOTES-v2.0.0.md).

A production fault injection found that the selected Windows task returned to
Ready after its WSL maintenance process was killed. The task had a nonzero
result and configured failure retries, but the process was not restarted.
The GUI background host now waits 30 seconds and retries failed child launches
itself. A successful maintenance exit still stops it, including when the owner
sets `startup.enabled=false`. The installer reuses the task name in the verified
installation receipt and restores its managed availability/retry settings.

## Upgrade

Use the verified Release Bootstrap for the selected existing installation.
On the Windows client, run the Release's `scripts/acs_windows_startup.ps1`
with the existing distribution, Runtime owner, installation root and full
machine ID. Preview first, apply and read back the same task. An existing
custom task name is resolved from its owner receipt automatically.

No database migration is required from v2.0.0. Keep existing credentials,
Node/Runtime/Slot identities, Journals and source configuration. Upgrading a
separate receiving node requires its normal signed deployment procedure;
updating the owner's installation does not synchronize a remote clone.

## Verification scope

Native Windows tests compile the actual GUI host and exercise failed-child
retry, successful exit, executable admission, PowerShell parsing and recorded
task-name preservation. Production checks use the existing authenticated ACS
entries and unique bounded messages. Windows Codex and Linux OpenCode run in
independent model contexts and receive explicit replies from the real remote
Codex engineer. The verifier reads committed communication; it never turns
Native terminal output into a reply.

Actual host reboot, client restart and process-crash observations are recorded
separately in the release verification evidence. Service restart alone is not
host reboot evidence. Raw model reasoning, credentials and private backups are
excluded from public release assets.
