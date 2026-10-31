# Owner OpenCode Native receiver

`runtime_deployment.receiver_opencode:callbacks` binds OpenCode to an enrolled
Node/Runtime and the current receiver deployment policy. It uses the existing
signed receiver transport and `NativeDeliveryAdapter`; it does not introduce a
task domain, terminal collector or background SSE execution observation.

The factory accepts only `access_mode=owner`. A Shared deployment needs its own
qualified restricted profile; selecting this factory cannot relax that boundary.

The required private settings are:

```json
{
  "schema_version": "acs-receiver-opencode-factory/1",
  "binding_id": "REGISTERED_CAPACITY_BINDING",
  "capacity_attempt_id": "CAPACITY_ID",
  "executable": "/absolute/path/to/opencode",
  "cwd": "/authorized/working/directory",
  "driver_journal": "/private/runtime/driver.sqlite",
  "node_journal": "/private/runtime/node.sqlite",
  "runtime_id": "REGISTERED_RUNTIME"
}
```

`ACS_RECEIVER_DSN` comes from the private service environment. No credential is
part of a tool request or this settings object. The actual Node registration
selects the observer identity; each committed message's sender is independently
rechecked before dispatch, including Client-origin communication. Retired task
packets refuse Native invocation.

`home`, `config_root`, `data_root`, `state_root`, `cache_root` and `temp_root` can
select the user's actual environment. Current-account defaults honor its XDG
settings; a separately selected home derives its own roots. `agent` is optional.
`provider_id` and `model_id` must be supplied together or both omitted. Omission
lets OpenCode select from the chosen native environment rather than inventing a
model ID. Restricted Driver profiles keep their explicit pinned selections.

Preparation starts an owned loopback-authenticated OpenCode server, creates a
real Session and reads back its ACS binding metadata and directory. Configuring
a collaborator reports this observed Session separately from saved configuration.
Later status queries read the existing Session; they do not prepare another one.
Dispatch records its stable native message ID before the request and distinguishes
HTTP scheduling from exact message readback. Unknown outcomes do not redispatch.
Replies still require the recipient's own ACS MCP `send_message` call.

Windows uses its owned Job. Owner Linux uses a verified owned process group;
this does not claim subtree containment. Termination verifies the issued process
handle, birth and remaining group members. Service supervision and recovery must
also isolate any old capacity before replacing its generation.

The current local Linux/WSL preparation and model evidence is recorded separately
from any physical remote-host or Shared qualification. Temporary test environments
do not modify the selected account's normal configuration or switch a deployed
service. See the phase evidence for the exact supported runs and limitations.
