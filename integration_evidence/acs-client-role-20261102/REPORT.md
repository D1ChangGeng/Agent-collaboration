# Client identity, role boundaries and current owner context

This qualification follows the retained S00 identity/management semantics and
current S00–S024 communication boundary, particularly R03/R04/R05/R07/R08,
R24/R27/R28 and R32/R33. Long-term RSI research is outside this change.

Fresh Client directories incorrectly marked a legacy Root Slot sharing the
Principal as self; multiple Slots sharing a Principal could also both be self.
Self now uses the resolved communication address. Historical organization
declarations no longer override the configured role. Owner Route-scoped callers
cannot explicitly read or update sibling Routes. Client and Root project-wide
access remains, using the same live authorization as actual calls.

The physical ordinary Agent independently reported missing documents because
owner-local paths were interpreted on its receiving host. The user selected the
owner's current files as the source. The admitted read-only SSH connection
retains that source, advertises its operations and rechecks the existing
collaborator binding before and after reading. Native local files remain local.
No different source checkout is substituted.

Actual cross-host testing exposed a nested-read write-lock problem. Read-only
authorization now avoids a Project write lock while the peer reauthorizes that
same Project; mutations retain locking, revision checks and final live checks.

| Identity or boundary | Actual verification |
| --- | --- |
| Client | New local connection and controlled new web conversation: Client, no Slot, no Native requirement, current Root tools |
| Root manager | Actual bound stdio/MCP context; Root/Route configuration; peer-Root refusal |
| Route manager | Actual bound stdio/MCP context; ordinary member management; refused Route creation and sibling read/update |
| Ordinary Agent | Actual bound stdio/MCP context and management refusal; physical Native Agent independently reported its own role and replied |
| Current owner origin | Actual receiving-host MCP and cross-host SSH; six current documents independently hash-matched; context current |
| File restrictions | Native local filesystem retained; operations visible; writes, outside roots, wrong SSH key and revoked Grant refused |
| Technical recovery | Actual owned SSH child stopped and recovered with a new verified process identity; zero Native model invocations |

Windows regression passed 95 tests with 15 environment skips. The native Linux
component snapshot passed 948 with 828 explicit skips. Final native PostgreSQL
integration on implementation commit `051e78d73450a67b28e823fa0db947cd9f303082`
passed 472 with 11 opt-in/service skips. Actual SSH/revocation/recovery passed 10;
startup recovery passed 20. Later focused read-lock and connection-operation
tests are recorded separately in verification.json. Exact implementation CI is
[the qualification run](https://github.com/D1ChangGeng/Agent-collaboration/actions/runs/41411896278).

Role stdio/HTTP cases are actual protocol/PostgreSQL integration, not independent
model reasoning acceptance. The initial physical Native audit and read-only web
Client are separate actual model observations. Candidate file-origin probes
requested zero model invocations. Mounted Windows-source Linux checks initially
failed Git/ownership rules; an unchanged-byte native snapshot passed. SSH
StrictModes remained enabled. CI fixture and folded-command errors were fixed,
and the relevant tests were rerun.

Core/Project Schema remains 2 and the public tool catalog remains 12. Existing
Root, Project, Slot and history identities remain. Normal communication creates
no task state. Software qualification does not claim production has switched.
Installed-package, post-upgrade physical Native, retention and release-download
verification require separate production evidence.
