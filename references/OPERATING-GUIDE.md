# Agent Collaboration Operating Guide

This guide is the decision layer for the `agent-collaboration-setup` Skill.
Read it when a user asks to create, adopt, repair, upgrade, validate, or
understand an ACHP setup and the user's wording does not already identify a
safe deterministic command. It is intentionally separate from the scripts:
the Agent interprets intent and reality; the scripts perform bounded file
operations and report observable facts.

This guide describes the current v0.4 baseline. A statement marked
`documented`, `unverified`, `architecture-allowed`, or `unsupported` is not a
promise that the Skill can perform that operation.

## 1. What this Skill is

`agent-collaboration-setup` installs or maintains a repository-native ACHP
scaffold. It is a setup/configuration surface, not a resident collaboration
runtime. Once a target has been set up, normal work proceeds from that
target's `AGENTS.md` and `.agents/` files; do not reload this Skill merely to
plan, code, review, hand off, synchronize Git, or maintain knowledge.

The Skill can currently provide a bounded, deterministic lifecycle for:

- repository setup and validation;
- nested management Workspace setup in the same project Git repository;
- standalone Workspace setup for compatibility;
- Route identity and registry operations;
- explicit schema/metadata upgrades;
- selected ownership, marker, path, dry-run, and idempotency checks.

It does not, by itself, provide a Session broker, Endpoint manager, SSH
driver, direct message relay, source synchronizer, or durable execution
recovery service.

### Workspace placement

Default to a management root inside the same project Git repository as product
code. Standalone Workspaces remain supported for compatibility.

```text
Project Git Repository / Source Checkout Root
├── Product code
├── ...
└── Nested Management Root
    ├── AGENTS.md
    ├── .agents/
    └── Route directories
```

Track management documents, knowledge, and Routes in project Git commits with
product code. Local and remote clones retain the same relative layout, but Git
synchronization requires explicit operations. The manifest records
`collaboration_root_mode`, while Git carries the layout.

Keep the supplied nested root as the CLI target. The only parent write is its
scoped runtime exclusions in repository-root `.gitignore`, between
`# ACHP-NESTED:<relative path>:BEGIN` and
`# ACHP-NESTED:<relative path>:END`. Preserve all pre-existing parent rules and
blocks; parent repository scaffolding is not required. Nested roots have no
child `.gitignore`. For legacy manifests missing the mode, `adopt`/`repair`
preserve the manifest; explicit `workspace upgrade` inside Git migrates only a
known setup-only child ignore. Custom child rules require reviewed manual
consolidation and cause writes to be refused.

## 2. Core mental model

Keep these objects distinct. Do not create a new durable object merely because
a Session, process, machine, or chat window changed.

| Object | Durable meaning | What it is not | Current Skill boundary |
|---|---|---|---|
| **Root / Project Collaboration Workspace** | One long-lived management identity and control surface for a collaboration world | A source checkout, running process, or per-turn log | Workspace setup/registry is implemented narrowly |
| **Route** | One long-lived workstream, goal, or development line under a Root | A chat window, Engineer, machine, or Endpoint | create/adopt/list/validate/set-state/rename/upgrade are implemented narrowly |
| **Session** | A temporary Harness conversation/execution context | A Route identity or durable project state | Harness-owned; no Skill-level attach API |
| **Engineer** | A role/person participating in a Route | A specific Session or machine | Protocol concept; no identity service |
| **Execution Endpoint** | Where Route work is executed | The Route itself or a Git remote | Replacement/rebinding is a future contract, not a current command |
| **Source relationship** | Whether and how a Route relates to source assets | Message transport | Representable in documentation; no complete binding workflow |
| **Source access** | How source can be read or changed (local, shared, SSH, evidence-only, unavailable) | Source history or ownership | SSH/access probes are not implemented by this Skill |
| **Source synchronization** | How source changes move between locations (Git, shared checkout, transfer, manual) | Session messaging | Git policy is documented; synchronization is external to this Skill |
| **Source State Evidence** | Verified source facts worth preserving across Sessions | Live liveness, freshness, or Session progress | Optional Route-owned file; created only when justified |
| **Message Transport** | How collaboration messages travel (manual relay or verified automatic path) | Git synchronization | Manual relay is the portable protocol baseline; direct relay is unverified |

### Durable state rule

Persist only stable identity, ownership, lifecycle, and high-value verified
facts that future Sessions cannot cheaply recover from authoritative sources.
Keep current Session progress, live capability observations, process liveness,
temporary Endpoint availability, and conversation details in the current
Harness context. Do not add checkpoints or recovery metadata to make this Skill
look like a workflow engine.

## 3. Support vocabulary

Use these labels in reasoning and reports. Never collapse them into a generic
“supported” claim.

| Label | Meaning |
|---|---|
| **supported (narrow)** | The current Skill has instructions, deterministic mechanism, invariant validation, and representative local evidence for a bounded input shape. |
| **supported (protocol)** | The protocol defines a safe interaction pattern, but a provider-specific runtime adapter is not implied. Manual user relay is in this category. |
| **partial** | Some layers work, but at least one decision, validation, safety, or user-journey link remains incomplete. |
| **documented / unverified** | The repository explains a relationship or policy, but the actual environment or E2E behavior has not been verified. |
| **architecture-allowed** | The design can represent the concept; the current Skill has no complete operation for it. |
| **unsupported** | The current Skill has no honest mechanism or evidence for the requested capability. |
| **unknown / not-measured** | The fact is not available from the current context. Do not infer it from a Harness brand, path name, or historical record. |

The detailed status and evidence ledger is in
[CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md). The regression inventory is in
[SCENARIO-MATRIX.md](SCENARIO-MATRIX.md).

## 4. First invocation: observe before asking

When a user gives a natural-language request, do not ask for internal schema
fields or immediately choose a command. Use this order:

1. **Resolve the scope.** Determine whether the request concerns this setup
   Skill, a project runtime, a Route, or ordinary project work. If it is
   ordinary work after setup, stop using this Skill and follow `AGENTS.md`.
2. **Inspect the supplied context.** Read the current working directory,
   explicit target path, Git status when repository mode is relevant, and the
   smallest relevant existing `AGENTS.md`, `CLAUDE.md`, `.agents/manifest.json`,
   registry, Route metadata, and ownership markers.
3. **Classify the observed state.** Use the Root and Route tables below. A
   missing optional Source State file is not an error.
4. **Infer only safe facts.** Reuse explicit user statements and authoritative
   files. Do not infer a source baseline, Endpoint, transport capability, or
   project identity from a Harness name, historical path, or filename alone.
5. **Ask only behavior-changing unknowns.** A question is justified only when
   the fact cannot be discovered, cannot be safely inferred, changes the next
   operation, and is needed at the current lifecycle point.
6. **Preview.** Run the narrowest relevant command with `--dry-run` when it
   mutates a target. Review conflicts and ownership before applying.
7. **Apply deterministically.** Use the exact supplied Workspace path; do not
   use the repository command family against a management Workspace.
8. **Read back and validate.** Validate the resulting invariant, not merely the
   process exit code. Preserve the distinction between applied, refused,
   conflicted, and unverified outcomes.
9. **Report the stable state.** State the target path, operation, files changed
   or preserved, validation result, and any capability that remains unknown or
   unsupported.

### Facts to discover automatically

- current working directory and an explicitly supplied target path;
- whether the target exists, is a directory, is empty, or is a file;
- existing `AGENTS.md`, `CLAUDE.md`, `.agents/`, manifest, registry, markers,
  Route metadata, knowledge, references, and Source State;
- whether the target is a Git repository, its root, branch, HEAD, and dirty
  state when repository synchronization is actually in scope;
- existing Route IDs/paths and duplicate or collision conditions;
- ownership evidence and managed-file drift that the validator can observe.

### Facts that may be safely inferred

| User expression or observed fact | Safe interpretation |
|---|---|
| “为这个项目建立协作空间” | A Root creation request, after resolving the target path |
| “这个目录已经有资料，接入协作系统” | Existing assets; inspect and use safe adopt, not bootstrap |
| “把之前那条路线接进来” | Existing long-lived Route; inspect and adopt only if it is not registered |
| “继续原来的路线” | Preserve Route identity; this is Session attach/continuation semantics, not Route creation. Current Skill has no attach command. |
| “原来的工程师窗口没了，重新开一个” | Session replacement; do not create a new Route. Current Skill cannot broker the replacement. |
| “工程师换到另一台电脑” | Endpoint/machine change; revalidation is required in principle, but no current Endpoint replacement operation exists. |
| “消息由我来转发” | User-mediated relay is the selected message transport. |
| “没有 GitHub，但可以 SSH” | SSH may be a source-access option; do not infer GitHub, source sync, authorization, or current baseline. The Skill has no formal SSH adapter. |
| “代码以后才开始” | Root/Route structure may be ready while source relationship remains pending or unbound. |

### Questions that are usually justified

- “协作空间应放在哪个目录？” when no unambiguous target path exists.
- “这个目录里的现有内容是否都属于要接入的项目？” before adopting a
  non-empty directory with mixed ownership.
- “你要建立新的长期路线，还是继续哪一条已有路线？” when multiple
  Routes match and the user's wording is ambiguous.
- “当前要维护的是源码仓库，还是管理 Workspace？” when the path could
  safely be interpreted as either mode.
- “你能直接读取工程师实际修改的代码目录吗？如果可以，是本地、共享
  目录还是远程访问？” only when a source decision changes the next action.

### Questions to avoid

Do not ask for internal fields or facts that are already discoverable or do not
change the current operation: schema keys, optional Source State fields,
future Sessions, a preferred Git provider, a nonexistent Endpoint, or a
transport capability that the current Harness has not actually exposed.

## 5. Root state classification and operation choice

Classify the target before selecting a command:

| Observed Root state | Decision | Current operation |
|---|---|---|
| Target path is absent | Confirm the intended path and whether a new management object is wanted | `workspace bootstrap` for a Workspace; repository `bootstrap` only for a genuinely new repository |
| Existing empty directory | Confirm it is the intended collaboration object | Workspace bootstrap or repository bootstrap, according to mode |
| Existing non-collaboration assets | Preserve assets and add bounded managed setup | `workspace adopt` or repository `adopt`; preview first |
| Current valid Root | Do not set it up again; interpret the user's actual next goal | `validate`, Route operation, or an honest unsupported/unverified response |
| Legacy schema 0.2 Root | Preserve readable state and make migration explicit | `workspace upgrade` / relevant `route upgrade` |
| Partial or conflicting Root | Inspect the exact gap and ownership before writing | `repair` only for a safe managed gap; otherwise stop and ask or require explicit upgrade |
| Path is a file, traversal escapes, malformed marker, or duplicate identity | Fail closed | No mutation; report the concrete refusal |
| Unrelated directory merely containing `AGENTS.md` or `.agents/` | Treat as a candidate, not proof of Route identity | Inspect/confirm before registration; never silently claim it is a Route |

### Root operation boundaries

- `bootstrap` establishes a new object only when the mode and target state make
  that safe.
- `adopt` adds bounded setup to existing assets and preserves project-owned
  content.
- `repair` restores a missing, clearly managed setup component; it is not a
  permission to overwrite arbitrary project edits.
- `upgrade` is the explicit schema/metadata migration boundary.
- `validate` reads and reports invariants; it should not be used as evidence of
  Session attach, Endpoint health, or source freshness.
- `uninstall` is guarded for Workspaces and destructive modes require explicit
  authorization and ownership evidence.

### Exact-path and validation boundary

All Workspace and Route command entry points use the exact supplied Workspace
path and reject a path that traverses a symlink, junction, or other reparse
point. `workspace validate`, `route ...`, and `--list-candidates` apply the same
guard as Workspace setup writes; none of these commands silently follows an
alias to a different management Root.

## 6. Route state classification and operation choice

| Observed Route state | Decision | Current operation or response |
|---|---|---|
| New long-lived workstream | Create a new durable identity | `route create` |
| Existing long-lived Route not registered | Adopt in that Route's own migration window | `route adopt` |
| Registered Route and user wants to continue | Keep identity and read Route instructions/knowledge | Attach is a semantic requirement; no current Skill attach command |
| Legacy Route metadata | Canonicalize metadata only | `route upgrade` |
| Registered Route health check | Read current files and registry | `route validate` / `workspace validate` |
| Missing managed Route component | Distinguish Root-owned and Route-owned gaps | Root `workspace repair` restores Root-owned files. There is no standalone `route repair`; `route adopt` previews and creates only missing canonical Route scaffold files while preserving existing Route-owned content. |
| Endpoint, machine, or Session changed | Preserve Route identity and re-evaluate runtime/source facts | No current Endpoint or Session replacement mechanism; label unverified/unsupported |
| Collaboration behavior or topology changes | Treat as explicit migration, not metadata upgrade | No current collaboration migration command |

Never create a Route merely because:

- a new Harness window was opened;
- an Engineer Session was replaced;
- a machine or Endpoint changed;
- a user asked to “continue”; or
- a source checkout moved.

## 7. Deterministic command map

Use the command family that matches the object. These commands do not decide
the user's semantic intent for you.

| Intent after observation | Command family | Required boundary |
|---|---|---|
| Add ACHP to an existing repository | `project_setup.py adopt --root <repo>` | Preserve project files; preview and validate |
| Initialize a genuinely new repository | `project_setup.py bootstrap --root <repo>` | Confirm target semantics and empty/new state |
| Change managed repository templates | `project_setup.py upgrade --root <repo>` | Explicit migration; preserve project-owned knowledge |
| Restore a missing managed repository file | `project_setup.py repair --root <repo>` | Verify ownership and avoid replacing intentional edits |
| Check a repository | `project_setup.py validate --root <repo>` | Report validator scope; do not claim runtime support |
| Adopt or initialize a management Workspace | `project_setup.py workspace <mode> --root <workspace>` | Use the exact supplied management root; nested mode may update only its scoped block in the repository-root `.gitignore` outside that root |
| Create a new Route | `project_setup.py route create --workspace <workspace> ...` | The path must be absent unless the same complete Route is already registered as an idempotent no-op; use `route adopt` for existing work |
| Adopt an existing Route | `project_setup.py route adopt --workspace <workspace> --path <route> [--route-id <id>]` | Preserve Route-owned files and state; a valid existing `route.yaml` supplies its durable custom `route_id` when the CLI ID is omitted |
| Canonicalize Route metadata | `project_setup.py route upgrade ...` | Metadata migration only |
| List/health-check Routes | `route list` / `route validate` | Registry/file facts only |
| Continue an existing Route in a new Session | No current command | Read existing context, preserve identity, and state that attach is not provided by this Skill |
| Replace an Endpoint or machine | No current command | Do not synthesize durable Endpoint state; require an independently verified procedure |
| Use SSH or direct relay | No current Skill command | Mark architecture-allowed or unverified; do not claim supported |

## 8. Source and message topology

Keep these dimensions orthogonal:

1. **Management/execution placement:** where the Workspace and actual work
   happen.
2. **Filesystem relationship:** shared directory, separate clone, remote path,
   or evidence-only view.
3. **Source relationship:** bound, pending, unbound, or unavailable.
4. **Source access:** local read/write, shared checkout, SSH, evidence-only, or
   unavailable.
5. **Source synchronization:** Git, shared filesystem, transfer, or manual
   procedure.
6. **Source evidence:** which verified facts justify a durable baseline.
7. **Message transport:** manual relay or an exact, verified automatic path.

GitHub is not a setup prerequisite. A Git remote is not proof of current
source access, and SSH access is not proof of Git synchronization. A successful
message send attempt is not proof of delivery or execution. Unknown capability
stays unknown until observed in the current Harness context.

### Current truthful boundary

- Manual user relay: supported at the protocol/policy level.
- Git synchronization: documented contract; execution depends on the user's
  repository and Harness environment.
- SSH source access: architecture-allowed/documented, not a current Skill
  mechanism or E2E-verified capability.
- Direct relay, Session enumeration/targeting, and cross-Harness runtime
  collaboration: unverified or unsupported by this setup Skill.
- Optional Route Source State: use only for verified source facts with durable
  cross-Session value. Never fill it with live Session, Endpoint, liveness, or
  freshness observations.

## 9. Validation and final reporting

Validation must prove the target invariant and must be scoped to what the
validator actually checks. For a setup operation, read back:

- exact target path and object identity;
- required managed files and markers;
- manifest/registry/Route metadata coherence;
- ownership preservation and conflicts;
- schema/version compatibility;
- dry-run non-mutation when previewing;
- repeated-operation convergence when idempotency is claimed.

For a Route, also check the required scaffold and the Root registration. The
absence of optional Source State is valid when no durable source fact has been
verified.

Do not turn a green setup validator into claims about:

- Session attach or replacement;
- Endpoint reachability or machine health;
- source freshness, branch synchronization, or push completion;
- SSH access;
- direct message delivery;
- another Harness's runtime behavior.

Use a completion report shaped like:

```text
Object: <repository | Workspace | Route>
Path: <exact path>
Intent interpreted as: <create | adopt | upgrade | repair | validate | unsupported>
Operation: <command or no command>
Changed: <files or none>
Preserved: <project-owned files/state>
Validation: <checks and result>
Runtime/source/transport facts: <verified facts only; otherwise unknown/unverified>
Next action: <stable next step or explicit user decision>
```

If a requested journey lacks a mechanism, say so plainly and preserve the
long-lived identity. Do not invent a new Route, write a runtime checkpoint, or
imply that a design document supplied the missing evidence.

## 10. Representative playbooks

### New management Workspace

1. Resolve the exact Workspace path.
2. Inspect whether it is absent, empty, or contains unrelated assets.
3. Preview `workspace bootstrap` or `workspace adopt` as appropriate.
4. Apply only after conflicts and ownership are clear.
5. Run `workspace validate` and read back the Root manifest/registry.
6. Create a Route only when the user has a distinct long-lived workstream.

### Existing management Workspace

1. Read the Root profile and registry before asking which Route to use.
2. If the user names an existing Route, preserve its identity and inspect it.
3. If the Route is unregistered but clearly long-lived, use its own adopt phase.
4. If the Route is already registered, do not run create; the current Skill has
   no attach command, so report the semantic gap and continue from existing
   `AGENTS.md`/knowledge when the Harness can do so.

For an unregistered or registered partial Route, `route adopt --dry-run` lists
the missing canonical scaffold files without writing them. Applying the same
operation creates only those missing files, preserves existing `AGENTS.md`,
knowledge, references, Source State, and other Route-owned content, and then
validates the completed Route. Root `workspace repair` remains scoped to Root
setup and does not silently take ownership of Route-owned gaps.

### Existing repository

1. Inspect existing instruction files and project ownership.
2. Use repository `adopt`, not `bootstrap`, for a populated project.
3. Preview, apply, validate, and review the diff.
4. Preserve project-owned knowledge, tasks, handoffs, source, and history.

### User asks to “continue” after a new window or machine

1. Map the request to the existing Route, not a new Route.
2. Read the existing Route identity and authoritative knowledge.
3. Keep Session/Endpoint facts in current context.
4. State that this Skill does not implement Session attach or Endpoint
   replacement. Do not fabricate a successful rebind.

### User mentions SSH or a remote Engineer

1. Ask only whether the next action requires source inspection, artifact
   retrieval, or message relay.
2. Distinguish SSH source access from Git synchronization and message transport.
3. Verify the exact current capability outside this setup Skill if authorized.
4. Until a real probe and read-back exist, label the capability unverified or
   unsupported and do not create durable runtime metadata.

## 11. When no current operation exists

Use this response shape internally and in the user-facing report:

```text
The request maps to <semantic lifecycle>, and the existing <Root/Route>
identity should be preserved. The current setup Skill has no deterministic
operation for that lifecycle. I will not create a replacement identity or
persist runtime-only state. The available next step is <read/validate/manual
relay/external verified procedure>, with the missing capability left
unverified until evidence exists.
```

This is an honest completion boundary, not a request to expand the Skill into
a runtime orchestration platform.
