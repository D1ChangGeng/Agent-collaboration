# Agent Collaboration System v1.4.0

2026-10-03

ACS v1.4.0 brings Authority connection clocks, focused installation verification,
consistent caller waiting, and explicit organization and responsibility
metadata to the collaboration Runtime.

## Authority time and observation

Connection Clock calibrates UTC through the authenticated PostgreSQL Authority
connection and carries offset, RTT, uncertainty and binding provenance.
Freshness uses a conservative UTC interval; new observed facts use a fresh raw
Authority sample. Local duration budgets use monotonic time, including Linux
suspend handling. IANA presentation settings provide display values alongside
canonical data. The Authority reference requires stable operation.

Existing signed timestamp encoding and durable command, nonce and consumption
identities remain compatible. See the
[time model](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/docs/runtime/TIME-MODEL.md).

## Installation and client setup

Independent prerequisites and selected Harness version probes run concurrently.
The same installation reuses its static probe snapshot while verifying current
service health, Runtime imports and authorization. Tool discovery uses one
membership scan and transaction, with live per-tool permission checks.

Machine setup verifies one actual MCP discovery, `read_profile` and
`list_projects` per selected client. Project initialization then reads its own
`load_project` context. Deep diagnostics remain available for all visible
projects. The
[installation timing guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/docs/INSTALLATION-PERFORMANCE.md)
describes the scope and readback fields. Whole-install duration still depends
on the host, dependency caches, image downloads and network.

## Send, wait and business validity

Async send returns after Message commit. Sync sends and response waits observe
the selected final response or condition by default. Optional caller timeouts
return pending handles; cancelling an observation releases its worker while
committed work, response tracking and notification continue. Client transport
limits can also end a call; retain response handles for Inbox recovery.

ACS derives Message business expiry from Scope/Team Policy, Work budget and
Grant horizons. The default Scope TTL is 24 hours, narrowed by applicable
horizons; an explicit deadline can further narrow it. Waiting preferences,
execution controls and internal operation budgets have separate responsibilities.
See the
[Send/Wait contract](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/docs/runtime/SEND-WAIT-LIFECYCLE.md).

## Agent organization and responsibility

Organization responsibility extent and functional duties are expressed
separately. Team records can declare `organization_level` and combined
`responsibilities`, retaining their primary role, selected Profile and explicit
Grant. Context and collaborator readbacks describe current Slot/Scope,
declared authorization and assignment, Review and Session lookup relations.

**Task Agent remains proposed terminology.** The organization proposal uses it
as the collective task-responsibility term alongside Root and Route. Existing
entities and identity cardinalities continue to define the concrete bindings.
Independent Reviewer and Finalizer acceptance guards remain active. See the
[organization proposal](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/docs/runtime/AGENT-ORGANIZATION-MODEL.md).

## Install or upgrade

Give the [v1.4.0 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.4.0)
to the local Agent. Verify the standalone `acs_bootstrap.py` against
`SHA256SUMS.txt`, then use `--version v1.4.0`. Reuse the recorded machine,
account/home binding, selected clients and web-access choice. The owner
completes required system or account authorizations.

The revised MCP catalog is a **guided upgrade boundary** for existing
installations. Automatic checks report the changed contract for review before
activation. Automatic upgrade preference, existing identities and rollback
state remain preserved. Reconnect clients after activation and verify the
selected installation's profile, project list and intended project context.
Runtime receiver deployments regenerate their reviewed callback/configuration
binding for the selected version and recalibrate on connection/boot replacement.

Service and account setup follow the
[getting started guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/docs/GETTING-STARTED.md).
ChatGPT account actions use the owner's external browser, with required login,
permissions, key handling and connection consent completed by the owner.

The project retains
[Sustainable Use License 1.0](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.4.0/LICENSE).
