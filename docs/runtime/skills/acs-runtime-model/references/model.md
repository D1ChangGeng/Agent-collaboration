# Runtime model

## Identity and persistent registration

Machine identifies a host. Node is the machine-side ACS service with boot and
incarnation identity. Runtime is an execution environment. Harness is the
external Agent product. Driver maps lifecycle operations to its installed native
API. Session is a replaceable native context. Endpoint is a logical delivery
target; Connection records an authenticated path to it. Attempt is one
WorkItem execution try.

The Node owns local observations, mailbox and journal. The Domain Authority
owns project state, authenticated command transitions and accepted state.
Drivers report native facts; external Agents decide work and acceptance.

In owner mode Connection, Node, Runtime, Endpoint and Session bindings persist
through disconnection until an explicit lifecycle change or revocation. Process
and Session readiness are read at execution time. A stopped or changed process
requires reconnection or preparation under the current binding. Shared
deployments retain configured registration and capability windows.

## Native environment and control

Native Codex and OpenCode modes select the actual user's environment and project
directory. Tools, MCP servers, plugins, provider, models, project configuration
and approval configuration follow that selection. Codex reads the chosen
approval_policy. The Driver accepts server_request_handler for native approval
or information requests; the standard headless Receiver factory leaves this
hook unconfigured and the transport replies -32601. Interactive capability
depends on the actual client handler and native decision/response readback.

Receiver process mode belongs to its signed deployment. Surface/database
activate_owner_mode preserves identity and continuous records. Existing
unspecified Receiver process mode remains shared. Owner/native Receiver
activation constructs matching factory/configuration digests, signs the next
Endpoint revision with the original Node key, commits it, then restarts and
reads back mode, digest and Session while preserving revocation state.

An attached binding names the exact native Session and transport. Session read,
send and cancel use that API and correlated operation identity. Owned process
or containment identity is required for process termination. Registration,
native acknowledgement, response, cancellation and process termination have
separate observations.

The ordinary POSIX owner supervisor records `owned_process_group` and
`subtree_containment=false`. Its termination proof covers that process group.
A containment claim requires the actual supervisor and receipt for that scope.

## Time and protected resources

Explicit business deadlines and shared admission windows use canonical UTC and
the applicable authenticated Authority clock. Local durations and transport
timeouts use monotonic time. Replay protection uses durable request identity,
signed receiver state, revisions, nonces and generations.

A Lease binds the owner Attempt, concrete resource, generation and fencing
token checked by its resource gateway. An uncertain effect requires readback
before another protected action. Historical terminal timestamps and hashes
retain their original values.

See `docs/runtime/OWNER-RUNTIME.md` for owner semantics and
`docs/runtime/TIME-MODEL.md` for bounded-operation clock behavior and evidence.
