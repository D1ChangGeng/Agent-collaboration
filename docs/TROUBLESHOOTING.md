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
| Account-page navigation awaiting browser control | Owner client machine, external browser, actual Harness control capability and given setup authorization | Use the owner's external browser within the authorized scope, or follow the official link and exact page/action/result instructions. The owner confirms login, permissions, secret entry and connection consent; the Agent waits for completion, then verifies actual MCP calls. |
| Tunnel healthy but ChatGPT tools unavailable | Running service, connection discovery and actual web MCP results | Refresh the selected connection, rerun the exact web readback and keep readiness scoped to observed results. |
| Automatic upgrade controls unavailable | Installed Release version and Bootstrap entry | Existing v1.2.0 installations need one AI-guided upgrade with the verified v1.3.1 Release Bootstrap. |
| Automatic checks delayed | Enabled policy, last result, next check, actual scheduling backend and host/user manager state | Wake the Runtime host, restore its owner scheduler if needed, or start a new stable-launcher MCP connection; use `--update --apply --force-check` for an immediate retry. |
| Cron registered but checks absent | Owner crontab entry and host cron daemon state | Verify the daemon on the Runtime host; connection catch-up remains available when enabled. |
| Update reports `review_required` | Major version, compatibility contract and rollback hold | Ask the setup Skill to review the candidate and preview a guided upgrade. |
| Update reports `failed` | Release integrity, managed-file ownership, locked environment, provider health and existing Grant authorization | Resolve the failed prerequisite, then repeat the installed Bootstrap's `--update --apply --force-check`; the active version remains available. |
| New version installed but session still uses the previous version | Active state and the running MCP process | Start a new connection through the stable launcher; restart the selected Tunnel's MCP process when appropriate. |
| Remote client Skills still show the previous version | Selected client host and Skill ownership | Refresh those Skills through setup maintenance on that client host. |

Keep credentials in the operator's private environment. Share redacted
diagnostic state, source identity and receipt handles when requesting support.

For deferred or interrupted ChatGPT setup, ask the setup Skill to connect the
existing ACS installation to ChatGPT web. The Agent regenerates the plan with
`scripts/acs_web_setup.py --choice enable --runtime-root <release-directory>
--config <private-surface-config> --json` on the confirmed Runtime host, adds the
selected `--tunnel-id`, and resumes from observed state. For a managed
installation, add `--installation-root <installation-root>` with the active
Release directory and matching private config to generate the stable launcher
command for that Tunnel profile. It performs client
configuration, service checks and diagnostics, and explains remaining owner
page actions in the owner's external browser on their client machine. Browser
control requires verified OS or external browser capability in the current
Harness and uses the owner's given setup authorization for navigation within
its scope. Seek further authority only when the intended operation requires it.
When control is unavailable or the owner
prefers guided steps, provide official links, exact pages and current labels,
actions and expected results, then wait for confirmed completion. Public
documentation can be retrieved read-only independently of those account actions.
Verify actual ChatGPT `read_profile` and `list_projects` before
reporting web readiness; verify `load_project` after registering a project.

Inspect automatic upgrade status with the installed Bootstrap's
`--set-auto-update status` on the recorded Runtime host as its owner. It reports
the policy separately from the observed backend state. Network or update errors
become eligible for retry after an hour; sleeping hosts and inactive user
managers affect execution. To recover through a retained previous Release, run
`--rollback --apply` and verify new MCP connections. The rejected version is
held for explicit review before the same version can be applied automatically.
See [automatic upgrades](AUTOMATIC-UPDATES.md) for the controls and eligibility
checks.
