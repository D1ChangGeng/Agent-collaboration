# Installation verification and timing

Machine installation establishes the selected Runtime host, services, owner
identity, selected client connections and optional web route. Project setup is
its next lifecycle.

## Standard path

1. Discover environment options and obtain the Runtime host, selected clients
   and web-access choice. Reuse decisions already given in the session.
2. Preview and apply the verified Release Bootstrap with the exact machine,
   account and home binding. Keep archive hashes, ownership, authorization,
   service health and rollback checks.
3. Reuse the install receipt for machine health and local authorization. Verify
   each selected client's actual MCP connection once: `tools/list`,
   `read_profile`, `list_projects`. Bundle these three reads in one connection
   when the Harness permits it. Read capabilities from the catalog and Skills.
4. Report enabled capabilities, selected machines, clients, services, web state,
   automatic upgrade status and pending owner confirmations. Initialize a
   project when the user chooses one, then verify its `load_project` context.

Functionality that requires a WorkItem, a team, native invocation or Review
belongs to the corresponding project workflow and release acceptance tests.
Installation smoke verification uses the three read-only connection checks.
Full tool-by-tool, model invocation and engineering Gate testing have their own
validation entrypoints.

## Implementation changes

| Cost source | Standard implementation |
| --- | --- |
| Sequential version checks with individual 10-second bounds | Independent prerequisite and selected Harness probes run concurrently |
| Repeating those checks after setup | The same install operation reuses its static prerequisite snapshot; Runtime imports, service health and authorization remain fresh |
| Probing unselected service-host Harnesses | Runtime-only setup probes prerequisites; client setup probes the selected Harnesses on their own hosts |
| One membership scan / transaction for every discovered tool | One scan and transaction per discovery, with live per-tool permission checks and fresh authorization at invocation |
| Loading every project during machine setup | Machine readback checks profile/projects/tools; combined setup reads only its newly registered project |
| Repeating capability discovery across standalone commands | One selected client connection carries the initial three reads |

There is no persistent authorization cache. OAuth discovery narrows the same
batch by the token's current scopes. Revocation is checked at the next
discovery and every actual tool call. An installation with no projects exposes
its profile and project-discovery entry tools.

`acs_doctor.py --config <private-config>` reports machine readiness by default.
Use `--project-id <id>` for one registered context or `--deep` for all visible
contexts during diagnosis. `--harness codex` narrows version probes.
Readback reports `validation_scope`, `tool_probes_reused` and monotonic
`elapsed_seconds`; these measure diagnosis, rather than download or total
installation time. Downloading dependencies and first-use container images
still depends on the host, caches and network.

Parallel-probe regression uses a concurrency barrier; discovery regression
requires a single transaction and then verifies a revoked permission is no
longer advertised. These verify removed work and preserved authorization.
Whole-install timing should be measured separately for cold and warm hosts
using the same Release, selected clients and dependency state.
