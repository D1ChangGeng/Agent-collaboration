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

Keep credentials in the operator's private environment. Share redacted
diagnostic state, source identity and receipt handles when requesting support.
