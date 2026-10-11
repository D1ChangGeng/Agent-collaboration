# Runtime decision map

Use persistent registration to discover the intended Node, Runtime, Connection
and Endpoint. Before invocation, inspect actual process and native Session
state, verify the current identity and reconnect or prepare the selected user
environment. A stored registration is a routing fact; fresh readback establishes
readiness.

Choose native execution when the Agent should use the selected user's tools,
MCP servers, plugins, project configuration, provider, model and approval
configuration. Confirm the installed native API supports the requested operation.
For Codex interactive approval or information requests, inspect the actual
server_request_handler binding. Standard headless factory uses the transport's
-32601 response; an interactive client needs its authorization and native
response handler.

For an existing Receiver's owner/native migration, preserve the original
profile, credential, keys, Node identity and revocation. Bind the new mode and
factory settings to a new deployment digest, sign and commit the next Endpoint
revision with the existing Node key, restart with the matching process config
and read back mode/digest/Session. Surface/database owner adoption has its own
separate identity transition.
An API-oriented integration follows the same identity and readback model.

Replace a Session while preserving Project, Route, AgentSlot, WorkItem and
Message identity. Replace an Attempt when execution identity changes. Session
cancel acts on the correlated native operation. Process stop requires the
confirmed owned process or containment.

Use a Lease when a real shared resource gateway requires a specific ownership
claim. Confirm which operations and resource that gateway fences. Resolve an
old owner before replacement where the resource cannot enforce fencing.

For uncertain effects, read the external authority's marker and result before
adopting, compensating or authorizing another Attempt. Check an explicit
business deadline and revocation at the actual boundary; shared mode also
applies configured permission, budget and expiry rules.
