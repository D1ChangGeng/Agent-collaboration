# Troubleshooting

Start with `scripts/acs_doctor.py` in the exact downloaded checkout. Supply a
Management Root path with `--project` and an existing Runtime surface config
with `--config` when those resources are available. The report identifies the
detected tools and, after Runtime configuration, the active Profile, Grant,
projects and discovered tools.

| Observation | Check | Recovery |
| --- | --- | --- |
| Source backend unavailable on Windows | Linux or WSL Runtime environment and exact Git checkout access | Move the Source/CAS service to the admitted Linux environment, then repeat project registration and MCP readback. |
| Linked worktree Source registration rejected | The worktree Git control directory, common object directory and authorized Source roots | Admit the exact Git metadata locations alongside the checkout, then repeat the guarded registration preview. |
| Local providers unavailable | Docker Compose availability, engine state and the selected owner-local service profile | Have the Agent install or start the engine with your system approval; rerun the readiness and service health checks. |
| Project missing from MCP | Management Root identity, Git source revision, registration preview and Domain membership | Complete the guarded project registration and read back `list_projects` and `load_project`. |
| Tool denied | Current principal, Profile, Grant, project_id, scope and expiry | Ask the Root Agent to inspect the required permission and request an authorized Grant change. |
| Target work delayed | Inbox, endpoint observation and receipt state | Read the same message handle and recover through `check_inbox` or a bounded wait. |
| ChatGPT Tunnel unavailable | Tunnel client health, Platform organization and workspace association, app connection | Follow the current [official Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) and test the exact local stdio MCP process. |
| Web setup awaiting a choice | Bootstrap `chatgpt_web` selection | Choose `enable`, `skip` or `later`; the Agent resumes setup with the explicit choice. |
| Web setup prepared but awaiting owner action | Generated web plan and its pending actions | Follow the [private Tunnel runbook](runtime/P2-PRIVATE-TUNNEL-PROFILE.md); complete the named account action, then let the Agent continue configuration and readback. |
| Tunnel healthy but ChatGPT tools unavailable | Running service, connection discovery and actual web MCP results | Refresh the selected connection, rerun the exact web readback and keep readiness scoped to observed results. |

Keep credentials in the operator's private environment. Share redacted
diagnostic state, source identity and receipt handles when requesting support.

For deferred or interrupted ChatGPT setup, ask the setup Skill to connect the
existing ACS installation to ChatGPT web. The Agent regenerates the plan with
`scripts/acs_web_setup.py --choice enable --runtime-root <release-directory>
--config <private-surface-config> --json` on the confirmed Runtime host, adds the
selected `--tunnel-id`, and resumes from observed state. It performs client
configuration, service checks and diagnostics, and explains remaining owner
page actions. Verify actual ChatGPT `read_profile` and `list_projects` before
reporting web readiness; verify `load_project` after registering a project.
