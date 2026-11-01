# Shared Codex receiver

`runtime_deployment.receiver_codex:callbacks` supports the qualified Linux
Codex 0.163.0 communication profile with a systemd user manager. Use the
existing signed receiver registration and `acs-receiver --factory-binding`
workflow. Owner retains the operator's selected Native environment.

The factory pins the executable, binary-generated experimental protocol schema,
private `CODEX_HOME/config.toml`, model-catalog provenance file and source
commit/tree. Select `permission_profile=achp-engineer` and
`collaboration_server=acs`. The catalog provenance file is not automatically
configured as a replacement Codex model catalog. Review any actual selected
model/provider configuration separately.

The named profile has exactly these filesystem entries: `:minimal=read`, the
absolute selected cwd with `read`, and the exact Codex executable with `read`.
The last entry lets Codex execute its own sandbox helper without granting its
entire installation HOME. Set the profile's `network.enabled=false`,
`default_permissions=achp-engineer` and `approval_policy=never`. Do not mix
legacy sandbox settings or startup overrides into this profile. Disable
`multi_agent`, `multi_agent_v2`, `shell_tool`, `request_permissions_tool`,
`apps` and `plugins` explicitly.

Configure exactly one required local MCP entry with an absolute command and
this ordered `enabled_tools` list:

```json
["read_profile", "list_projects", "load_project", "list_collaborators", "check_inbox", "list_messages", "read_message", "send_message", "wait_for_response"]
```

Shared project-scoped discovery omits `list_projects`. Startup requires the
other eight tools, rejects tools outside this allowlist and verifies the actual
MCP connection, six disabled features, selected allowed permission profile,
read-only network-disabled sandbox, cwd and Native Session identity.

Supply at most 16 explicit `environment_refs` using `ACS_` names and ordinary
private references, for example `ACS_B_CREDENTIAL`, `ACS_B_DSN` and the selected
provider's `env_key`. Credentials stay out of command arguments and public
evidence. The restricted child gets a minimal environment; inherited proxies
and runtime injection variables are rejected.

Use a private HOME and temporary directory beside `codex_home`. The systemd
environment directory is
`/run/user/<uid>/acs-receiver-codex/receiver-run-<32 lowercase hex>/systemd-env`.
The supervisor enforces 64 tasks, 1 GiB memory, 100% CPU, `NoNewPrivileges`,
`ExitType=cgroup` and group-wide termination. The qualified physical host has
the reviewed `/opt/acs/codex-sandbox/bin/bwrap` helper. An unavailable OS sandbox
is a failed qualification; it is not evidence of a permission denial.

History and authorization checks precede a final current-status read. The
two-second local idle lease starts at that final request's dispatch; the
signed transport observation retains its independent 15-second bound. The
Driver checks the target again before `turn/start` and never implicitly steers
a busy target. A possible Native effect remains uncertain and is not retried.

Qualification uses two real model contexts, the receiving Agent's ordinary
MCP reply, actual permission-executor positive/negative probes and owned
process cleanup. Command probes use the administrative `command/exec` endpoint
with the same profile; that endpoint is not exposed as a model tool by ACS.
The receiver has no terminal collector or Native event subscription.

The [qualification evidence](../../integration_evidence/acs-codex-shared-20261101/REPORT.md)
binds the tested binary, source bytes and limits. Windows Codex Shared Native
and other binary versions need separate qualification. Codex protocol reference:
[App Server](https://learn.chatgpt.com/docs/app-server),
[permissions](https://learn.chatgpt.com/docs/permissions).
