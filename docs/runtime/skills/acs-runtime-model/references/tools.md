# Runtime tool map

- list_connections reads Node, Tunnel, provider and endpoint connections.
- list_harnesses reads eligible capacity and expiry evidence.
- list_collaborators shows current Session and Harness bindings for AgentSlots.
- stop_attempt requests Attempt-level control and returns Driver acknowledgement
  plus effect state.
- read_resource reads Attempt, Lease, Effect or capability handles when exposed
  by the active Profile.

Runtime tools remain filtered by Grant and Profile. Operator-level raw Domain
commands use submit_command.
