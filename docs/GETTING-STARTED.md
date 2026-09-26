# Get started with Agent Collaboration System

Give the [repository link](https://github.com/D1ChangGeng/Agent-collaboration)
to a local Codex or OpenCode session and ask it to guide the installation.
The Agent can inspect your operating system, local tools, project repository and
existing ACS setup, then perform the supported setup actions. You choose the
project location and collaboration goal and complete system or account approvals
shown by your machine or service provider.

## Agent launch request

> Use this repository as the ACS distribution source. Inspect its current
> release and installation instructions, verify the downloaded source or
> package, then install and validate ACS for this machine. Ask me only for
> project intent and approvals that I must perform. Show me the installed
> components, connected Harnesses, projects, active permissions, available
> collaboration tools and one practical next step. Help me create or adopt a
> Management Root in my project and tell me where to open its Root Agent session.

The Agent should inspect the exact version and current instructions from the
repository. The source checkout provides read-only diagnostics through
`scripts/acs_doctor.py` and a guarded plan/apply entry through
`scripts/acs_install.py`. The current source also contains the explicit
project identity and Source registration procedures in
[Runtime project adoption](runtime/PROJECT-ADOPTION.md). A complete installation
report requires direct Runtime readback with `read_profile`, `list_projects`
and `load_project` after registration.

The Source/CAS backend requires Linux. On Windows, have the Agent choose an
admitted Linux or WSL Runtime environment, verify access to the project's
Git checkout there, and connect the local Harness to that Runtime. The Windows
client path needs its own cold-start readback before it is reported as ready.
For a linked Git worktree, the Agent must also locate and explicitly authorize
its Git control directory and common object directory. The Source service
checks both paths through pinned directory handles; granting only the worktree
directory leaves its Git metadata outside the admitted Source boundary.

The local installer reports `local_authority_ready` after the Python environment,
Skills, PostgreSQL, Temporal and private owner Authority are checked. For a clean
committed Source, it also registers the project and reports `project_registered`
with a live context readback. The Agent completes any project commit and then
configures MCP clients. It reports readiness after actual MCP calls pass.

## Start a project

The Management Root belongs inside your project source checkout. Ask the Agent
to inspect the project, create or adopt the Root, and preserve current project
instructions and knowledge. After setup, open Codex or OpenCode with the
Management Root as its working directory. The Root Agent reads its `AGENTS.md`,
project identity and Route registry. Tell it the collaboration goal and ask it
to create the first Route and Team.

For a first collaborative task, ask the Root Agent to create a WorkItem, hand
the work to an authorized AgentSlot, inspect the message receipts, wait for a
response or recover it from Inbox, then request an independent Review of the
resulting evidence. The Agent should report exact source commit and tree,
delivery state, reviewer identity, unresolved items and the next authorized
action before accepting work.

## ChatGPT web connection

For an individual installation, the [single-user private Tunnel profile](runtime/P2-PRIVATE-TUNNEL-PROFILE.md)
connects ChatGPT to the owner's local ACS MCP process. The owner completes
OpenAI Platform Tunnel permissions and ChatGPT developer-mode connection.
The Agent checks current official [Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
and [ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt)
guidance, configures the local process, and verifies its ACS Grant and project
readback. Access to the Tunnel follows the owner's Platform organization and
ChatGPT workspace association.

## Installation report

Ask the Agent to report these observed facts after setup:

| Area | Readback |
| --- | --- |
| Source | Release tag, commit, tree and distribution digest |
| Local services | PostgreSQL, Temporal, ACS Runtime and MCP health |
| Project | `project_id`, Management Root, Routes and SourceBinding |
| Access | Principal, Profile, Grant expiry and visible tools |
| Harnesses | Codex and OpenCode connection and actual tool discovery |
| Continuity | Message receipt, Inbox recovery and Review path |
| Next action | The exact project directory and Root Agent prompt |

The report distinguishes installed files, configured connections and observed
runtime behavior. For setup problems, use the diagnostic output and the
[troubleshooting guide](TROUBLESHOOTING.md).
