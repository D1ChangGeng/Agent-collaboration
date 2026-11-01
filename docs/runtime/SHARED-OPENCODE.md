# Shared OpenCode receiver

`runtime_deployment.receiver_opencode:callbacks` accepts an explicitly pinned
Shared profile on Linux with a systemd user manager. Owner installations keep
their selected native environment. Shared configuration is an operator setting;
ordinary Agents continue to use the normal ACS communication tools.

Use the existing `acs-receiver --factory-binding --factory-reference
runtime_deployment.receiver_opencode:callbacks --factory-settings <private-file>`
workflow and signed Node/Runtime/Endpoint registration. Preserve the original
receiver keys and journals during an upgrade. A Shared receiver's registration,
grants and command proof must all remain current for the requested lifetime.

The one-use Node challenge must still be fresh when its registration commits.
The explicitly requested Endpoint lifetime is bounded by the active Node,
Runtime and Grants. It can outlive that consumed challenge; model initialization
does not shorten the registered resource to the nonce's admission window.

In addition to the normal factory fields, the private settings require:

| Field | Value |
| --- | --- |
| `executable_sha256` | SHA-256 of the selected OpenCode executable |
| `opencode_version` | Qualified version, including `1.18.34` |
| `schema_path`, `schema_sha256` | Absolute reviewed OpenAPI file and its SHA-256 |
| `config_sha256` | SHA-256 of `config_root/opencode/opencode.json` |
| `agent`, `provider_id`, `model_id` | Explicit selection matching global and agent configuration |
| `collaboration_server` | One local MCP server name, such as `acs` |
| `systemd_environment_dir` | `/run/user/<uid>/acs-receiver-opencode/receiver-run-<32 lowercase hex>/systemd-env` |
| `environment_refs` | Optional explicit environment-name to private-reference map; at most 16 entries |

Create distinct private HOME, configuration, data, state, cache and temporary
directories. Data/state/cache/HOME/temp must be empty before first launch.
Do not reuse an interactive OpenCode HOME for this profile. Pin an independently
reviewed schema, such as the distribution's
`runtime_tests/schema-1.18.34/opencode-openapi.json`; the Driver compares its
contents to the actual server's `/doc` response.

Both global and selected-agent permissions must contain `"*":"deny"`,
`"task":"deny"` and exactly these allowed MCP tool names, replacing `acs` with
the selected server name:

```json
{
  "acs_read_profile": "allow",
  "acs_list_projects": "allow",
  "acs_load_project": "allow",
  "acs_list_collaborators": "allow",
  "acs_check_inbox": "allow",
  "acs_list_messages": "allow",
  "acs_read_message": "allow",
  "acs_send_message": "allow",
  "acs_wait_for_response": "allow"
}
```

The configuration must have an empty plugin list and exactly one enabled local
MCP entry with an absolute executable in its command vector. That entry must
authenticate an ordinary ACS engineer bound to the receiving Slot. Its MCP
surface uses Shared access mode and the configured project/tenant authority.
Keep credentials in private references, outside commands and public artifacts.
The child receives a minimal environment plus the explicit references; inherited
proxy/runtime override variables are rejected by the restricted profile.

Startup verifies executable, schema and configuration pins before invoking the
owned process. The Driver then checks the actual version, effective permissions,
connected MCP server and real Session identity/permission/selection readback.
It starts OpenCode with `--pure`. The Linux supervisor enforces 128 tasks,
1 GiB memory, 100% CPU quota and a 10-second stop budget, with `NoNewPrivileges`
and cgroup-wide termination. The communication receiver subscribes to no Native
execution events and does not turn terminal output into replies.

The pinned operator configuration is loaded explicitly. Native-generated SDK
metadata and caches live under the private state directory; they do not relax
the closed operator configuration directory. Native default plugins are disabled.
The signed cross-host readiness observation is bounded to 15 seconds, including
authorization and receipt persistence. Immediately before invocation the receiver
obtains a new two-second local idle lease. Both leases remain bounded by any
explicit business deadline and current enrollment/authorization checks.

Cold MCP initialization has a bounded 60-second HTTP allowance. Configure the
sender's existing `request_timeout_seconds` for the actual network; the qualified
cross-host test uses 30 seconds. A timeout preserves uncertainty rather than
inventing a Session or repeating a possible invocation. These limits qualify
this reference configuration; they are not a model throughput guarantee.

Current evidence and untested combinations are linked from the release notes.
Windows Shared OpenCode requires separate qualification and is refused by this
factory. Codex retains its independently versioned Shared profile contract.
