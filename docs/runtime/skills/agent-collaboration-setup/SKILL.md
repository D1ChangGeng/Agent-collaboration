---
name: agent-collaboration-setup
description: Install ACS on a confirmed local Linux, named SSH, or named WSL Runtime host; connect selected Codex/OpenCode client hosts; separately create or adopt project Management Roots and configure web connections.
---

# Agent Collaboration Setup

The discoverable installed setup Skill is the repository's root
[SKILL.md](../../../../SKILL.md), distributed by `scripts/install_skill.py`.
This file records its Runtime setup contract. Machine installation establishes
a private owner Authority on a confirmed service host and connects selected
clients. Project Management Root setup is a separate lifecycle that users can
request when they begin a project.

Canonical mechanisms: `acs_bootstrap.py` release digest verification and host
selection, `acs_install.py` bounded Linux host setup, project setup CLI,
`acs_web_setup.py` machine-specific web planning, `read_profile`, `list_projects`,
`list_connections` and `load_project`.

1. Inspect the caller host, active Harness and current ACS installation.
2. Confirm the Runtime placement before writes: local Linux, a named SSH target
   or a named WSL distribution. Resolve the client hosts and Codex/OpenCode
   connections. Ask for the host choice only when the user has not supplied it.
3. Confirm the ChatGPT web choice after machine selection: enable now (`enable`),
   local clients only (`skip`) or configure later (`later`). Ask when missing and
   pass the explicit result through Bootstrap's `--chatgpt-web` option.
4. Probe that exact host read-only and record machine identity, account,
   home directory, prerequisites and transport reachability. Pin the full
   machine identity, account and home directory before directory or service
   mutations. Bind apply to the preview's `--expected-machine-id`,
   `--expected-account` and `--expected-user-home`; supply all three values.
5. Preview and apply the selected Release's Bootstrap with `--runtime-host`,
   matching `--ssh-target` or `--wsl-distribution` and `--harness`. Verify the
   published archive SHA-256 and packaged file manifest before executing the
   Runtime installer. The bounded local Runtime installer receives
   `--host-confirmed` and runs from the full
   verified Release. SSH/WSL use `--runtime-only` to install services and scoped
   owner credentials. Local Linux defaults to selected client setup on the same
   host and also supports service-only `--runtime-only`.
6. Install setup and knowledge Skills and configure MCP on selected clients'
   own hosts. For SSH/WSL, use the returned caller-side stdio descriptor. The
   Runtime host can be explicitly selected as a client. Preserve configuration
   rollback copies and validate actual tool discovery, `read_profile` and
   `list_projects` from each client. An empty project list is a valid machine
   installation state.
7. For `enable`, follow [the private Tunnel runbook](../../P2-PRIVATE-TUNNEL-PROFILE.md).
   Fetch current official account and connection guidance, generate the exact
   Runtime-host plan with `acs_web_setup.py`, execute install/init/doctor/run,
   and configure recoverable service persistence. Explain required owner login,
   permission, private-key entry and ChatGPT connection confirmations. Verify
   actual web `read_profile` and `list_projects`; project setup can follow later.
   For `later`, record the same route's resume entry.
8. Report Runtime machine identity and account, version/commit/tree, services,
   credential references, client connections, verified tools and rollback data,
   plus the web choice, observed connection state and exact pending owner actions.
9. When the user requests project setup, first discover the actual local,
   authorized SSH or selected WSL Source checkout and compare existing bindings
   using [Source discovery](../../SOURCE-DISCOVERY.md). Preserve or create `project_id`,
   Management Root, manifest, AGENTS managed block, Routes and knowledge. Bind
   clean committed Source under reviewed scopes, validate identity coherence
   and read back `load_project`. Preserve existing Root/Route identity.
10. When web access is enabled or the user resumes deferred setup, configure the
    selected remote HTTPS or private-Tunnel MCP profile. For the
    single-user private Tunnel, retain the owner's existing ACS Grant and bind
    a local stdio process. For remote HTTPS, configure OAuth metadata. Present
    current SaaS account and authorization actions to the user.
11. For enabled web access, verify profile and project access from the selected
    client type. Record
    changed files, service state, credential references, rollback data and user
    actions needed for account permissions.

Machine binding records Runtime installation placement and client transport.
Runtime Node enrollment and cross-host execution require independent live
Node/Driver observations.

Normal project work proceeds through the installed AGENTS context, runtime
Skills and MCP tools. Setup is invoked again for installation maintenance,
project adoption, connection changes, validation, repair, upgrade or removal.
