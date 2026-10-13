# Owner Runtime contract

Status: accepted product behavior for the single-owner installation.
Implementation and deployment claims remain bound to the code, configuration
and verification evidence of the installed release.

ACS connects an installation owner's Agents, projects and native Harness
Sessions. The owner configures collaborators, submits durable work and messages,
reads the current workspace, reviews results and controls the execution objects
that ACS actually owns. The Runtime records authenticated commands and applies
deterministic state transitions; external Agents decide goals, delegation,
review and acceptance.

## Installation and access

A new single-owner installation writes `access_mode: owner` to its trusted
service configuration. This selects continuous owner access to active service
and project objects. The owner can also choose `access_mode: shared` for a
deployment with per-subject Grants, Policies and budgets.

Every owner operation checks:

1. the credential from the trusted transport or enrollment context;
2. the authenticated tenant, principal, Authority and Authority incarnation;
3. the active service and any addressed Project, Scope or target object;
4. explicit identity, Node, Connection or object revocation;
5. stable request identity and canonical input for deduplication;
6. the expected revisions and operation-specific prerequisites.

Body fields select an object and identify the request. Trusted context supplies
the caller identity. The Runtime resolves each typed handle within its tenant
and Project before reading or changing the object.

Owner identity remains active until explicitly revoked or removed. Compatibility
records can retain identity references and audit lineage. An elapsed historical
Grant timestamp does not require the owner to renew each project, role or
machine registration.

Transport security remains part of both access modes. Remote connections verify
TLS and the registered certificate or key, signed sender identity, Authority
incarnation, Node identity, current binding revisions and replay state. OAuth
resource servers validate token issuer, audience, subject, scopes and token
expiry. Credential rotation and explicit revocation apply at the actual
boundary.

## Collaborators and responsibilities

Project, Root, Route, Scope, AgentSlot and WorkItem have durable identities.
Machine, Runtime, native Session, transport and directory are replaceable
bindings. Root and Route describe responsibility extent. Engineer, Reviewer,
Specialist and Finalizer describe duties.

An ordinary owner team member supplies `agent_slot_id`, `principal_ref`,
`role` and `harness_requirements`. Team changes supply `project_id`, the
existing Scope handle, `client_request_id` and `expected_revision`.
Optional organization metadata describes combined responsibilities and a
Profile describes the client view.

For example, an owner can configure an engineer with:

```json
{
  "client_request_id": "team-engineer-1",
  "project_id": "project-example",
  "scope_handle": "scope:project-example:scope-main",
  "expected_revision": 0,
  "members": [
    {
      "agent_slot_id": "engineer-1",
      "principal_ref": "agent:engineer-1",
      "role": "engineer",
      "harness_requirements": ["codex"]
    }
  ]
}
```

Roles organize the work. Owner team configuration stores these business
bindings directly. Candidate-specific reviewer identity and independence remain
separate acceptance checks. A changed team revision preserves the previous
configuration and the provenance of work already performed.

## Persistent registration and actual readiness

Connection, Node, Runtime, Endpoint and HarnessSessionBinding records remain
registered until an explicit lifecycle change, replacement or revocation. A
registered Endpoint identifies where ACS should reconnect; its recorded state
alone does not establish that a process or native Session is ready.

Before execution, ACS reads the actual process, transport and native Session
state. It reconnects to the current authenticated binding and prepares the
selected environment when needed. A stopped process, busy Session, changed Node
boot or unavailable provider becomes an observed readiness condition. Pending
work and registration remain available for recovery.

Execution records distinguish registration, live observation, dispatch,
native acknowledgement, response and termination. Process birth identity,
owned containment and native Session readback establish the object being
controlled. A Harness name or stored PID alone is insufficient evidence.

## Operation status

Owner responses describe the boundary that needs attention:

| Result or error | Meaning |
|---|---|
| `identity_mismatch` | The request identity differs from trusted context |
| `service_identity_inactive` | The installation's service identity is unavailable |
| `scope_unavailable` | The addressed collaboration Scope is unavailable |
| `identity_revoked` | An identity was explicitly revoked |
| `business_deadline_elapsed` | A command's explicitly chosen business deadline elapsed |
| `message_expired` | The Message's explicit business deadline elapsed |
| Revision or idempotency conflict | Current object state or submitted input differs |
| Pending or uncertain execution | Readiness, native acknowledgement or result needs readback |

Resolve the reported state using its current object and operation handles.
A pending delivery can recover through the registered binding and Inbox.
An explicitly revoked identity requires an authorized lifecycle decision.

## Durable commands, messages and waiting

Owner commands and messages have an optional business `deadline`. Omission
or null keeps the request valid while its service, target and initiating
identity remain active. An explicitly supplied timezone-aware deadline is
checked at admission, dispatch, retry and result application where applicable.

Caller waiting and internal operation timeouts are separate durations:

| Setting | Purpose |
|---|---|
| Command or Message `deadline` | Optional limit chosen for the business request |
| `response_mode: async` | Default: return committed Message, response and notification handles |
| `response_mode: sync` | Commit the same Message and wait for its target condition |
| `wait_until` | Select a receipt or terminal condition; default is `response_received` |
| `wait_timeout_seconds` | Optional early return for a synchronous send |
| `wait_for_response.timeout_seconds` | Optional early return while observing any or all response handles |
| Driver, database or transport timeout | Bound one internal operation and support recovery |

An omitted caller timeout waits until the selected condition completes, a
terminal result is observed or the call is interrupted. Zero performs one
observation. A caller timeout or disconnected client leaves the committed
Message, response tracking and subscription available. Reconnect with the same
handle, read the Inbox or resume waiting.

Retries retain the logical Message and original command lineage. Reusing a
`client_request_id` with equivalent submitted input returns the prior result;
different canonical business input conflicts. Response mode and caller wait
settings are observation preferences for the same submission.

Owner stdio MCP services configured with `temporal_endpoint` automatically maintain
already committed Messages through Temporal while the service entry is running.
The ordinary new installer records the selected local Temporal address and
port. A custom service with that setting omitted retains pending Outbox state
for a separately operated dispatcher. Report the configured address and actual
worker/dispatch readback when describing automatic delivery.

Owner remote recovery follows the persistent work intent. A temporary remote
outage keeps the committed Message available for another readiness, connection
and dispatch attempt. Temporal RPC failures reconnect the delivery maintenance
loop while the management MCP service remains available. Explicit revocation or
an elapsed chosen business deadline records the affected Message's own terminal
outcome. The remaining project-management operations keep their current service
and identity checks.

Outbox and Inbox state are durable. Delivery facts remain distinct:
`accepted_by_authority`, `target_inbox_committed`,
`runtime_dispatched`, `runtime_acknowledged` and `response_received`.
Notifications use the actual active MCP Connection and Session binding. The
client's advertised notification or wake capability selects the immediate
path; `check_inbox` recovers the same durable state in a later Session.

## Terminal response readback

Current `response_received` receipts and recorded `fenced_late` observations
identify their terminal response digests and original Dispatches. The Receiver stores the corresponding native result
as a Scope Artifact. Core retrieves missing bytes through the existing signed
`delivery.readback` operation.

Each signed chunk binds the original Message, operation, Attempt, Dispatch,
Endpoint and Node identity, together with the response digest, offset and total
size. The Receiver validates that binding against its recorded terminal
observation and reads the matching Artifact. Core checks chunk offsets and
bounds, verifies the assembled SHA-256 against the terminal receipt, and stores
the bytes in the corresponding configured Scope CAS.

Owner `read_message` for a response handle and `check_inbox` first complete
their preliminary Project authorization transaction. They then prepare missing
Core response Artifacts through remote readback and perform the formal read in
a fresh authorized transaction. Remote I/O occurs between those Project
transactions; query, transfer and final read retain their applicable explicit
revocation checks.

Later reads use the verified Core cache for an already copied historical
result. The formal read checks current Project/Scope access and Artifact
integrity. Response handles, original native identity, receipt digests and
historical timestamps remain attached to the recorded result.

Owner `read_message` can return `historical_responses` for `fenced_late`
observations. Each entry retains its original `attempt_id`, `dispatch_id`,
native outcome, observed time, result content and Artifact digest. Its history
identity remains separate from the current task, admitted Attempt and delivery
receipts. Missing historical bytes are retrieved by that exact original
`dispatch_id` through the same signed chunk transfer and Core Scope cache.

## Native Codex and OpenCode environments

Native execution selects the owner's real user environment and project
directory. The Harness resolves its tools, MCP servers, plugins, project
configuration, provider, models and approval configuration from that
environment. Codex reads the selected config's `approval_policy`; an explicit
selection is supplied to the native thread, and other native settings retain
their installed behavior.

Interactive native requests have a separate client interface. The Codex Driver
accepts `server_request_handler` and forwards it to `JsonRpcClient` for
approval or information requests. A handler must obtain the applicable
authorization and return the native API's response. The standard headless
Receiver factory leaves this hook unconfigured: the transport records the
server request and replies with JSON-RPC error `-32601`. Describe interactive
approval capability using the actual installed API, handler binding and response
readback. OpenCode likewise follows the operation and decision interfaces its
installed native client exposes.

Drivers map ACS operations to the installed Codex App Server or OpenCode API.
Version and capability checks establish the concrete operation the API can
perform. API-oriented integrations remain compatible with this model.

An attached binding identifies an exact native thread or Session and an
authenticated transport. ACS reads that Session, submits a message or invokes
its turn, and cancels the correlated native operation through the actual API
where supported. Busy state and native acknowledgement are read back before
the next action. A lost acknowledgement is reconciled using the existing
operation identity and native history.

Process termination requires a verified ownership relationship to the process
or containment being stopped. Session cancellation and owned-process termination
are distinct controls; their receipts record the native result and any
remaining uncertainty.

The Windows owner Receiver uses an owned JobObject with `max_processes=None`
by default. Process birth identity, JobObject ownership and verified termination
still bind stop control to the processes actually owned by that Receiver.

The ordinary POSIX owner supervisor controls its recorded process group. Its
receipt reports `scope: owned_process_group` and
`subtree_containment: false`. Descendants that create a separate process
session are outside that group's stop proof. A stronger containment profile
requires the corresponding supervisor and verified containment receipt.

## Machine filesystem and Source reading

Owner machine tools operate on the selected machine's current files under its
connected OS account. `read_file` requires `path`; `list_directory`,
`glob`, `grep`, `write_file`, `edit_file` and `apply_patch` provide
the corresponding discovery, search and change actions. Each accepts optional
`machine_id` and `cwd`.

`filesystem_context` reports the actual machine, OS account, platform, home,
cwd and connected choices. `select_filesystem` sets this MCP instance's
selected machine and its directory. A single call's overrides retain their
local scope. The default `local` target is Core's service OS account, with
its home as the default cwd unless installation settings choose another
directory. A Core running in WSL therefore uses the WSL account and paths.

Paths follow the target OS, including absolute and home-relative paths, parent
directories, ordinary links, Windows drive paths and UNC paths. Account
permissions govern access to hidden, ignored and untracked files, binaries,
large files and paths outside repositories. Account or container isolation
implements a selected deployment boundary. File service readiness is independent of native Harness
Session activity.

Read/search output is delivered under the effective `max_output_bytes`
budget, with `complete` and `next_cursor`. The cursor keeps the actual
machine, directory, path and query across changes to the session default.
Machine responses report the actual account, path and observation time.
[The machine filesystem guide](MACHINE-FILESYSTEM.md) defines schemas, ranges,
write semantics, transports and errors.

SourceBinding describes the project's repository, readable locations and
recommended versions. An Agent chooses an available machine, Native, Git,
repository MCP or other reader according to its actual connection and access.
Reading location and execution Node have separate bindings.

The Project's primary product source identifies its repository checkout.
`primary_source_id` selects that product Source hint.
`primary_source_root` identifies the preferred repository read location;
current Source reads resolve that repository's physical primary worktree,
observe its actual branch and include edits and admitted untracked files.

Owner Core `read_source`, `read_source_file`, `list_source_files` and
`search_source_files` can omit `source_id` and `revision`. These explicit
Source tools use the Source provider's configured readable roots:

| Selection | Source behavior |
|---|---|
| Project product default | Resolves the eligible product Source and reports its `primary_source_id` |
| Preferred repository location | Uses `primary_source_root` to resolve the physical primary checkout |
| Explicit `source_root` | Reads the selected current worktree within configured readable roots |
| Explicit `revision` | Reads an already captured commit or workspace snapshot |

A fixed commit or captured workspace view (`view_snapshot`) is an explicit
selection. Source readback includes `actual_source` with `provider`,
`root`, `commit`, `tree`, `view_revision` and `observed_at`. Record
these facts alongside the repository, branch and workspace state.
`list_sources.current_readable_root` reports the Source provider's location;
`origin_hint` supplies repository origin `host` and `path` guidance.

Owner `load_project.source_observation` describes the product Source.
`management_source_observation` records a distinct Management Root observation.
When a product default is unavailable, product observation and its
`primary_source_id`/`version_hint_ref` guidance are null. Management context
and explicitly selected management reads retain their own access checks.

Source pagination continues at the returned `view_revision` to retain byte
identity. A new current Source read can observe newer edits. Review and
acceptance retain the actual candidate, source and Evidence identities.
Source byte bounds, normalized paths, secret handling, tenant/Scope ownership,
revocation and digest readback apply at the Source provider's boundary.
Shared deployments retain their established `read_file`, `list_files` and
`search_files` schemas, access, permission and version checks.
Message delivery, source reading and Git synchronization have separate evidence.

## Results, Review and acceptance

Artifact bytes, execution receipts, Evidence claims, Review decisions and
accepted state are separate records. Deterministic storage and hashes retain
their exact identities. A hash establishes byte identity; execution and Review
evidence establish what those bytes demonstrate.

A Review names the candidate, source revision, criteria and reviewer
assignment. The adopted acceptance profile checks reviewer independence,
required evidence, the integrated baseline, protected effects, publication
readback and unresolved items before accepting work. Owner access changes
invocation admission; it preserves these candidate and integrity checks.

Completed facts keep their recorded author, source, Authority, binding,
timestamps and digests. Natural expiry of a historical Grant does not erase or
invalidate an already recorded execution, Artifact or Review. Explicit
revocation controls new actions. A claim about current readiness or current
source still requires a current observation.

## Protected resources

A real shared resource gateway can require a Lease with owner Attempt,
resource identity, generation and fencing token. The gateway verifies that
specific claim at the point of use. Such a lock covers the named resource and
the operations that pass through that gateway.

Native Harness tools continue under the selected user's environment and
approval configuration. An ACS gateway receipt demonstrates the gateway action
recorded in it; describe the protection and evidence at that scope. An
uncertain external effect requires readback of the existing result before
retry, adoption or compensation.

## Existing installations and migration

| Configuration | Access behavior |
|---|---|
| New single-owner installation | Installer records `access_mode: owner` |
| Explicit `access_mode: owner` | Continuous identity and registration, optional business deadlines |
| Explicit `access_mode: shared` | Per-subject Grant, Policy, Profile and budget governance |
| Existing configuration with no `access_mode` | Retains `shared` behavior until explicit migration |

Migration is an owner decision applied to trusted service configuration and
the compatible Runtime schema. It preserves Project, Root, Route, Source,
request, Artifact, Evidence and Review identities. Retain deduplication,
historical lineage, explicit revocation state and a recoverable configuration
baseline during the change. Confirm the mode returned by `read_profile` and
the active receiver configuration after restart or reconnection.

The explicit `activate_owner_mode(config_path)` adoption mechanism verifies
the private profile's credential, preserves its identity and stores the
original configuration as `.before-owner-upgrade` when switching modes. It
clears natural expiry on active, nonrevoked identity and registration records.
This helper migrates the trusted Surface configuration and database records.
Revoked or retired records retain their lifecycle state. Repeated adoption
reuses the preserved configuration and identities.

Receiver execution has its own signed process deployment. Existing unspecified
Receiver process configuration retains `shared`. To activate owner/native
execution for an existing Receiver:

1. Preserve the original process profile, credential, cryptographic key
   references, Node identity and revocation state.
2. Build a Receiver Runtime configuration with owner mode and the selected
   native factory settings. Compute the new deployment policy/configuration
   digest from that exact mode, factory and binding.
3. Use the existing Node signing key to bind and sign the updated Endpoint
   registration. Submit its new revision to the Authority with the expected
   previous revision.
4. Restart the Receiver using that matching process configuration, then read
   back the committed Endpoint revision/digest, actual native mode, Session and
   readiness.

The existing `bind_process_config` mechanism computes the deployment digest
and signs the matching Endpoint registration. The Authority registration and
process configuration advance together. Retain the original profile for
recovery; already revoked objects keep their recorded lifecycle state.

The installer can apply this owner adoption to a positively identified existing
private owner Root profile. An explicit shared configuration retains shared
behavior. Loading an unspecified configuration on its own retains the
compatibility default shown above.

Shared deployments retain their configured permission, expiry, budget,
challenge and protected-boundary rules. Internal transport timeouts and
cryptographic checks continue in both modes.

## ChatGPT connection metadata

An existing custom MCP connection can retain its discovered tool metadata after
a server schema update. The owner server exposes optional chosen deadlines,
create_work budget and caller wait timeout; verify those fields in the active
client's refreshed schema.

After starting the updated MCP server, open its existing connection in ChatGPT
Plugins, select **Refresh**, inspect the refreshed metadata, and start a new
conversation to rerun the affected operations. This is the official
[custom MCP metadata refresh](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata)
procedure.

The current cached-metadata web exercise supplied an explicit one-hour business
deadline and completed creation, remote execution and result reading.
Verification of omitted deadline and budget fields in that existing connection
follows its metadata refresh and a new conversation.

## Verification and related contracts

This document defines accepted behavior. Component tests, real database tests,
native Harness runs and cross-machine Gate evidence each support only the
source, configuration and scenario they measured. Runtime readiness, deployment
support and performance claims require their corresponding readback and
measurement.

Runtime public service exports resolve their concrete modules when those names
are used. Temporal sandbox preparation checks this import/preparation path.
Native invocation, signed delivery, terminal transfer and complete cross-machine
workflow claims retain the scope of the actual run that measured them.

The eight [ACS knowledge Skills](skills/README.md) explain the model and
decision rules by domain. [Send and wait](SEND-WAIT-LIFECYCLE.md) describes
receipt and observation mechanics; its automatic horizon derivation applies to
shared deployments. The [adoption contract](UPGRADE-CONTRACT.md) retains
architecture, Gate and acceptance requirements. Its Grant and time-window
requirements apply to shared admission or an explicitly bounded owner
operation. Exact tool inputs come from the active service catalog.
