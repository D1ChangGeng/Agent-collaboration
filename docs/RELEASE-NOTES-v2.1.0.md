# ACS v2.1.0

Shared authorization reads now use compatible row locks while retaining
revocation and policy-change fencing through commit. Concurrent ordinary
messages previously could deadlock; an independent receiver's enrollment check
could also wait on the configuring caller's own authorization lock.

The OpenCode receiver supports an explicit, pinned Linux Shared profile with
normal ACS communication. It permits nine exact ACS tool names, denies native
shell/file/task tools, pins the executable/configuration/OpenAPI/selection and
checks actual effective permissions and Session identity. A systemd user service
bounds the process tree and its resources. See the
[configuration contract](runtime/SHARED-OPENCODE.md).

Shared startup validates executable bytes before execution and observes the
version inside the supervised server. The factory no longer runs a separate
version probe that populates a fresh HOME. Native supervision uses a bounded
operation-derived process label. Both access modes keep communication independent
of Native terminal output and execution-event subscriptions.

Shared natural messages may omit a business deadline. The signed transport
readiness window is bounded to 15 seconds; the receiver refreshes a separate
two-second local idle lease before invocation. Status requests timestamp their
own observation after Session validation, instead of consuming the lease while
reading message history. Native SDK metadata uses private state while the
operator configuration directory retains its closed admission rules.

A Shared Endpoint's explicit resource lifetime is bounded by its current Node,
Runtime and Grants. The one-use Node challenge remains an admission check,
including a fresh check after registration locks; its short nonce window no
longer truncates the registered resource. Linux listener ownership inspection
also tolerates an unrelated process exiting during `/proc` traversal. Expired
capacity cleanup stops the proven owned process before releasing its claim.

No database migration is required from v2.0.3. Upgrade the existing Owner Runtime
and any separate receiver using their normal verified release and signed update
paths; retain credentials, keys, journals and communication data. Shared mode is
enabled only by an operator's complete restricted profile.

Qualification includes reverse physical Native, restricted Shared and sustained
MCP/PostgreSQL traffic. The release evidence records actual measurements,
retained failures and the precise limits of each run.
