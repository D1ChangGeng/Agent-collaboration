# Runtime tool map

- list_connections reads registered Node, Tunnel, provider and Endpoint paths.
- list_harnesses reads registered capacity and observed Harness or Session facts.
- list_collaborators shows Slot, Session and Harness bindings.
- stop_attempt requests Attempt-level control and records native cancellation
  or verified owned-process termination with remaining effect state.
- read_resource reads Attempt, Lease, Effect or capability handles exposed by
  the active service.
- submit_command exposes complete Domain commands for the admitted advanced
  client surface.

In owner mode a discovery result can report continuous binding lifetime and a
runtime state that has not yet been observed. Execute only after actual
readiness inspection, reconnection and preparation. Shared mode retains its
configured Grant, Profile, capability and expiry checks.

Attached native Session controls depend on the exact installed API. A
Session-level acknowledgement and an owned-process termination proof support
their respective controls. Keep their identities and receipts with the
Attempt.

Native Codex uses the selected approval_policy. Interactive native requests
depend on an actual server_request_handler passed to JsonRpcClient. The standard
headless Receiver factory uses the transport's explicit -32601 response.
Read the installed client/handler capability and native request/response facts
when deciding whether an interactive operation can proceed.

Receiver mode is bound to its signed process deployment and Endpoint digest.
Surface/database owner adoption preserves identity; Receiver owner/native
activation additionally commits the Node-signed replacement registration,
restarts the matching process config and reads back actual mode and Session.
