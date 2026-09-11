# Runtime Source and Sandbox contract

Status: adopted conditional Reference Profile. Contract revision: 2026-09-11.1. Authority: [Runtime
adoption](UPGRADE-CONTRACT.md) and [Driver contract](DRIVER-CONTRACT.md). Interface findings are source-reviewed. Deployment,
lifecycle and isolation conformance for this Profile are not_run; missing capability evidence is unknown. Admission requires the
actual checks below. Configuration presence establishes intent, not successful containment or a passed P1/P2 Gate.

## Authority and execution boundary

Source/Effect Gateway holds protected-source and external-effect authority. Every protected read/write/publish rechecks
authenticated scope, current Grant, policy, deadline, lease generation and fencing token, including retries. Engineers receive
their authorized source/artifact content and isolated scratch capacity. Shared source integration, publication and external
writes cross the Gateway; an Engineer must lack direct target credentials and alternate access.

Each Attempt has an exclusive Harness process, private state/configuration and an independent execution unit. A Session ID, cwd
or worktree is not an OS identity. Untrusted code runs in a restricted executor containing neither model nor publication
credentials, or in an equivalent complete isolation arrangement that passes credential and process-access tests. Credential
brokering and sandbox provisioning are required deployment choices, not implemented claims. Secret references identify
authority; they do not enforce process isolation.

Node materializes only authorized inputs, binds their baseline/digests and records outputs. A Git worktree may point to a shared
common-dir exposing other history and resources; use an authorized snapshot or an independently scoped repository. Source,
scratch, Harness state and protected targets have separate mount/ACL grants. Resolve aliases and links at the actual resource
boundary.

## Fixed integration evidence

| Target | Version | Official source revision |
|---|---|---|
| Codex / Windows | 0.152.1 | [5adb68a49933ae446bf11935662c83dba55a0804][c152] |
| Codex / Linux | 0.153.2 | [657a993cbee87acf52d14b758ce49dbd46d1b8eb][c153] |
| OpenCode / Windows | 1.18.27 | [4b7e19e315cca414121ba1d61523fef74bb3ae8b][o127] |
| OpenCode / Linux | 1.18.30 | [3104c1428ec91f809e5ab86631300de41eb6952e][o130] |

Bind every deployed Profile to executable/version, schema, configuration, effective tools, OS identity and sandbox/backend
evidence. Re-probe changes.

## Codex Profile

Legacy workspace-write grants filesystem-root read access and scoped writes. Its App Server SandboxPolicy exposes writableRoots,
networkAccess and tmp options, not a readable-root allowlist. Named permissions compile precise read/write/deny entries from a
restricted policy. [Policy source][cpolicy]

Node owns an isolated CODEX_HOME and immutable effective configuration. Use default_permissions and
`permissions.<name>.filesystem`; do not inherit the built-in :workspace read grant. This Linux example gives Harness tools only
system runtime reads and a prepared input directory inside the execution unit:

~~~toml
approval_policy = "never"
default_permissions = "achp-engineer"
allow_login_shell = false
web_search = "disabled"

[features]
multi_agent = false
multi_agent_v2 = false
shell_tool = false
request_permissions_tool = false
apps = false
plugins = false
recommended_plugins = false

[shell_environment_policy]
inherit = "none"
experimental_use_profile = false

[shell_environment_policy.set]
PATH = "/usr/local/bin:/usr/bin:/bin"
HOME = "/run/achp/home"
TMPDIR = "/run/achp/tmp"

[permissions.achp-engineer.filesystem]
":minimal" = "read"
"/run/achp/input" = "read"
~~~

Node substitutes exact authorized platform paths and necessary runtime values. :minimal includes system paths such as Linux
/etc; its deployed contents must be reviewed. Explicit write entries are admitted only for Attempt-local scratch. Linux bwrap
consumes the resolved readable roots. [Compiler][ccompile], [Linux][clinux]

Windows requires windows.sandbox="elevated" and actual successful readiness/setup plus an access probe. The unelevated
restricted-token backend cannot enforce split read or deny-read restrictions and rejects those cases. Elevated setup must
precede admission; a nested sandbox failure does not establish host backend availability. [Windows backend][cwindows]

Launch codex --disable multi_agent --disable multi_agent_v2 app-server. Node controls thread/start and thread/resume
config/sandbox/cwd and turn/start sandboxPolicy/cwd; packets cannot override them. Legacy policy replacement can rebuild read
grants, so preserve and verify the effective named Profile. shell_tool=false does not remove apply_patch, which has separate
registration. There is no reviewed universal native-tool allowlist: inspect the effective catalog and enforce remaining tools'
filesystem/network access. [Tool registry][ctools]

MCP policy fields are `mcp_servers.<id>.enabled`, enabled_tools and disabled_tools; the denylist follows the allowlist.
Plugin-server equivalents are under `plugins.<id>.mcp_servers.<name>`. Only verified Gateway endpoints and actual catalog names
may be admitted. Tool filtering does not constrain a server's own authority. Shell environment policy controls shell
subprocesses; Node must also build the Harness environment from an allowlist. [Configuration schema][cschema]

## OpenCode Profile

Launch opencode --pure serve with an isolated HOME and config/data/state roots. Set OPENCODE_DISABLE_PROJECT_CONFIG=1.
OPENCODE_CONFIG_DIR adds a directory; it does not replace other search locations. Node-owned configuration directories must
contain only approved data, with project configuration and custom code excluded from loading. --pure covers external plugins;
registry discovery still imports tool/tools JavaScript/TypeScript, including symlinks. [Paths][opaths], [Registry][oregistry]

Start global and selected-agent permission maps with "*":"deny", "task":"deny"; allow only verified Gateway tool names. Append
final session rule {"permission":"task","pattern":"*","action":"deny"}. Native shell and file tools remain denied in this
Profile. Rules use last-match precedence. Shell execution inherits process.env plus plugin additions and uses a native process
spawner; permission checks are not an OS filesystem sandbox. [Permissions][opermission], [Shell][oshell]

Node fixes allowed agent/model and canonical prompt parts. Reject tools overrides, agent/subtask parts, arbitrary file: URLs and
MCP resource parts. prompt.tools replaces session permissions; agent/subtask paths can bypass task checks. file: reading uses
bypassCwdCheck and a no-op approval callback; resource parts invoke MCP reads directly. Accept text or Gateway-authorized
artifact content with verified scope/digest and an explicitly allowed representation. [Prompt][oprompt]

Gateway MCP configuration uses `mcp.<id>.type="remote"`, url, enabled and oauth=false; resolve actual endpoint authentication and
allowlisted tool names from trusted binding/catalog evidence. Protect the native HTTP control surface against arbitrary session,
config, permission, command and shell requests. [MCP fields][omcp]

## Restricted executor and process supervision

A Docker-backed executor may use a pinned image digest, non-root UID, read-only root, exact input/scratch mounts, isolated
PID/network namespaces, cap-drop=ALL, security-opt=no-new-privileges:true and explicit resource limits. Offline code execution
uses network=none; required network access needs an enforced endpoint policy. Docker socket, host credentials, agents and
unrelated roots stay outside the execution unit. Node owns container lifecycle and Gateway owns dispatch, authorization and
output read-back. Docker availability/conformance is not_run. [Official Docker
interface](https://docs.docker.com/engine/containers/run/)

Windows Job Objects and Linux cgroups supervise processes and resource usage. Use kill-on-close, prohibit breakaway where
supported, and inspect descendants. Filesystem/network restrictions require independent OS/backend enforcement. Replacement
receives resource authority only after old-owner isolation or confirmed termination; an unfenceable live owner keeps admission
blocked. [Job Object semantics](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

## Real conformance matrix

All rows are not_run. Record requests, IDs, exits, effective settings, raw read-back and digests against the [Gate
contract](gate-contract.json). Synthetic sentinels supply test data; only actual Harness/OS/Gateway execution proves a row.

| ID | Actual exercise | Required evidence |
|---|---|---|
| S0 | Probe all four exact executables and effective configuration/tool catalogs. | Version/schema/backend identity; unsupported or unknown controls block admission. |
| S1 | Read/write another Scope via shell, Python/Node, native file tools, traversal, symlink/junction and Git common-dir. | OS/resource rejection; authorized input remains usable; canary bytes and metadata unchanged. |
| S2 | Place synthetic credential/env markers outside the executor; probe files, inherited environment, process interfaces, sockets and MCP descendants. | Markers unavailable to untrusted code; required Gateway call succeeds with scoped identity. |
| S3 | Run precise read policy on Windows elevated and unelevated backends. | Elevated readiness plus access enforcement; unsupported backend rejects execution; no unsandboxed fallback. |
| S4 | Submit config/sandbox/cwd/tools/agent/subtask/file/resource overrides and introduce project/custom-tool code. | Driver rejects before execution/loading; effective restrictions unchanged; native child inventory matches. |
| S5 | Attempt direct target access and old/expired/revoked-owner effects, including retry after policy change. | Alternate access fails; Gateway rejects stale authority at actual protected target. |
| S6 | Crash/cancel/terminate with long-running descendants and held handles, then replace owner. | Process/resource read-back proves isolation before replacement; unrelated capacity survives. |

Windows 0.152.1 exposes the direct probe syntax codex sandbox [OPTIONS] [COMMAND]... with -P/--permission-profile and -C/--cd.
Run the synthetic probe command under the named Profile from an appropriate Node execution context. Capture this binary's help
and effective policy; optional --sandbox-state-json, --sandbox-state-readable-root, --sandbox-state-disable-network and
--include-managed-config require explicit reviewed values for that probe. CLI help and schema generation alone do not satisfy
S1-S6.

[c152]: https://github.com/openai/codex/tree/5adb68a49933ae446bf11935662c83dba55a0804
[c153]: https://github.com/openai/codex/tree/657a993cbee87acf52d14b758ce49dbd46d1b8eb
[o127]: https://github.com/anomalyco/opencode/tree/4b7e19e315cca414121ba1d61523fef74bb3ae8b
[o130]: https://github.com/anomalyco/opencode/tree/3104c1428ec91f809e5ab86631300de41eb6952e
[cpolicy]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/protocol/src/permissions.rs
[ccompile]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/core/src/config/permissions.rs
[clinux]: https://github.com/openai/codex/blob/657a993cbee87acf52d14b758ce49dbd46d1b8eb/codex-rs/linux-sandbox/src/bwrap.rs
[cwindows]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/sandboxing/src/windows.rs
[ctools]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/core/src/tools/spec_plan.rs
[cschema]: https://github.com/openai/codex/blob/5adb68a49933ae446bf11935662c83dba55a0804/codex-rs/core/config.schema.json
[opaths]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/config/paths.ts
[oregistry]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/registry.ts
[opermission]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/permission/index.ts
[oshell]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/tool/shell.ts
[oprompt]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/prompt.ts
[omcp]: https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/core/src/v1/config/mcp.ts
