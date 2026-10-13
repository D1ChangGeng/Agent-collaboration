# Agent Collaboration System v1.5.1

2026-10-13

ACS v1.5.1 corrects owner identity reporting in machine readiness and upgrade
diagnostics. The standard Release Bootstrap can complete verification and
activation when an owner profile returns its trusted identity.

## Owner diagnostics

`acs_doctor.runtime_readback` reports the actual `access_mode`, trusted identity
and its lifetime. It accepts an optional Grant summary for owner access;
shared mode retains its configured Grant summary. Service authentication
continues to verify the configured credential. Project, Source and tool
readbacks preserve their existing behavior.

## Install or upgrade

Use the verified
[v1.5.1 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.1).
The Agent verifies `acs_bootstrap.py` against `SHA256SUMS.txt`, previews and
executes the installation on the recorded machine/account/home binding, then
checks the active profile and connections. Existing v1.5.0 installations use
this patched Bootstrap for guided readiness verification and activation.
Identity, configuration, explicit revocation and rollback data remain preserved.

## Verification

The regression covers an owner profile whose readback omits a Grant summary.
Candidate diagnostics against the published v1.5.0 Runtime and a real database
reported authorized owner access, identity lifetime `until_explicit_change`,
seven projects and 48 tools.

Runtime capabilities and package code match v1.5.0. See
[getting started](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.1/docs/GETTING-STARTED.md)
and the
[v1.5.0 capability notes](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/RELEASE-NOTES-v1.5.0.md).
