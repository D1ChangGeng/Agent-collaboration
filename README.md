# agent-collaboration-setup

A **setup-only, harness-agnostic Agent Skill** that installs and maintains the
**Agent Collaboration & Handoff Protocol (ACHP)** in either a source repository
or a long-lived Project Collaboration Workspace.

After setup, the skill gets out of the way.

Normal multi-agent work runs from:

```text
AGENTS.md
.agents/
```

—not from this Skill.

[中文 README](README.zh-CN.md)

## What this repository solves

Different agent harnesses expose different collaboration capabilities. Some can only read other sessions, some can send to sessions on the same machine, and some environments may support cross-machine relay. Those capabilities can also vary by version, permissions, deployment, or runtime.

ACHP therefore does not bind collaboration semantics to a harness brand.

It uses:

- **capability-based branching** for session relay;
- **manual user forwarding** as the universal safe transport;
- **automatic relay only when the exact required capability is positively verified**;
- **Git as the durable repository-state bridge**;
- **`.agents/knowledge/` as the durable project knowledge plane**;
- **`AGENTS.md` as the canonical runtime entry point**.

The Skill in this repository only installs/configures that mechanism.

## Design boundary: setup Skill vs runtime protocol

```text
agent-collaboration-setup (this Skill)
        |
        | bootstrap / adopt / upgrade / repair
        v
Repository project                 Project Collaboration Workspace
├── AGENTS.md                       ├── AGENTS.md       <- Root identity/router
└── .agents/                        ├── .agents/        <- Root control plane
                                    ├── Route A/        <- Route-owned state
                                    ├── Route B/
                                    └── Route N/
```

Once installed, ordinary project sessions do **not** need to load this Skill.

Use it again only when you intentionally want to change the collaboration setup itself.

## Portable Skill format

This repository follows the open Agent Skills `SKILL.md` format and keeps frontmatter to portable fields.

Current official discovery locations include:

| Harness | Recommended personal location |
|---|---|
| Codex | `~/.agents/skills/agent-collaboration-setup/` |
| OpenCode | `~/.agents/skills/agent-collaboration-setup/` |
| Claude Code | `~/.claude/skills/agent-collaboration-setup/` |

Codex and OpenCode can share the same `~/.agents/skills/` installation.

## Recommended installation: one clone, multiple harnesses

Clone this repository once into a stable source location:

```bash
git clone https://github.com/D1ChangGeng/Agent-collaboration.git ~/.local/share/agent-collaboration-setup
cd ~/.local/share/agent-collaboration-setup
```

Then expose that single checkout to all supported harnesses:

```bash
python3 scripts/install_skill.py --harness all
```

The installer uses symlinks where practical so a later `git pull` updates every harness at once. If symlinks are unavailable (commonly on some Windows setups), it safely falls back to copying.

Validate the installation:

```bash
python3 scripts/install_skill.py --harness all --check
```

### Install for only one harness

```bash
python3 scripts/install_skill.py --harness codex
python3 scripts/install_skill.py --harness opencode
python3 scripts/install_skill.py --harness claude
```

Codex and OpenCode intentionally resolve to the shared Agent Skills path.

### Windows

From PowerShell:

```powershell
git clone https://github.com/D1ChangGeng/Agent-collaboration.git "$HOME\.local\share\agent-collaboration-setup"
cd "$HOME\.local\share\agent-collaboration-setup"
py scripts\install_skill.py --harness all
```

If creating symlinks is not permitted, `--mode auto` falls back to a copy. Rerun the installer after `git pull` to refresh copied installations.

## Using the Skill

Invoke it only when setting up or maintaining ACHP.

Examples:

### New repository

```text
Use agent-collaboration-setup to bootstrap ACHP in this repository.
```

### Existing repository

```text
Use agent-collaboration-setup to adopt this repository into ACHP.
Preserve all existing project instructions and documentation.
```

### Upgrade

```text
Use agent-collaboration-setup to upgrade the ACHP setup in this repository.
Do not overwrite project-owned knowledge, tasks, handoffs, or project profile.
```

### Validate

```text
Use agent-collaboration-setup to validate this repository's ACHP setup.
```

Harness invocation syntax differs. For example, Codex can explicitly mention a Skill, Claude Code exposes Skills as slash commands, and OpenCode exposes them through its Skill system. The natural-language prompts above remain portable.

## Project Collaboration Workspace and Routes

A Workspace is a durable management/control root. It may be physically separate
from the source repository and execution hosts, and it is allowed to remain
non-Git.

```bash
python3 scripts/project_setup.py workspace adopt --root /path/to/workspace --dry-run
python3 scripts/project_setup.py workspace adopt --root /path/to/workspace
python3 scripts/project_setup.py workspace validate --root /path/to/workspace
python3 scripts/project_setup.py route list --workspace /path/to/workspace
```

Create a new Route without copying an existing Route:

```bash
python3 scripts/project_setup.py route create \
  --workspace /path/to/workspace \
  --path "C Route" \
  --route-id c-route \
  --display-name "C Route"
```

Adopt an existing Route only from that Route's own migration phase. Adoption
preserves its existing `AGENTS.md`, `.agents/knowledge/`, references, and state:

```bash
python3 scripts/project_setup.py route adopt \
  --workspace /path/to/workspace \
  --path "Existing Route"
```

The Root registry stores stable identity, path, lifecycle, and pointers. Dynamic
engineering status remains Route-owned. Source Repository and Execution Endpoint
fields start as `unknown`; historical paths or Harness names do not establish a
current baseline.

### Schema 0.2 operation boundary

The Workspace commands `bootstrap`, `adopt`, `upgrade`, `repair`, and `validate`
are implemented against the exact supplied path. `workspace uninstall` is
currently guarded: it refuses to change files until a reviewed ownership plan is
available. Route `rename` changes only the display metadata; it does not move the
Route directory or alter its registry path. Split/merge, path-moving rename,
Endpoint replacement, restore, and rollback remain future migration contracts
requiring explicit evidence, review, and a reversible recovery plan.

## Deterministic repository setup CLI

The Skill includes a standard-library-only Python setup tool:

```bash
python3 scripts/project_setup.py adopt --root /path/to/repo
```

Modes:

```text
bootstrap
adopt
upgrade
repair
validate
uninstall
```

Preview any mutating operation first:

```bash
python3 scripts/project_setup.py adopt --root /path/to/repo --dry-run
```

Validate after installation:

```bash
python3 scripts/project_setup.py validate --root /path/to/repo
```

Repository uninstall preserves project-owned coordination/knowledge by default.
The Workspace uninstall command is a separate guarded path and currently makes no
changes. For a source repository, to remove all ACHP data too:

```bash
python3 scripts/project_setup.py uninstall --root /path/to/repo --purge-data
```

## What gets installed into a project

```text
AGENTS.md
CLAUDE.md                     # only a thin @AGENTS.md compatibility route
.agents/
├── README.md
├── config.yaml
├── manifest.json
├── protocol/
│   ├── CAPABILITIES.md
│   ├── RELAY.md
│   ├── GIT-SYNC.md
│   └── KNOWLEDGE.md
├── coordination/
│   ├── PROJECT.md
│   ├── roles/
│   ├── tasks/
│   ├── handoffs/
│   └── templates/
├── knowledge/
│   ├── README.md
│   ├── guides/
│   ├── decisions/
│   ├── observations/
│   └── archive/
└── runtime/                  # ignored by Git
```

The installer uses bounded managed blocks in `AGENTS.md`, `CLAUDE.md`, and `.gitignore`. Existing content outside those blocks is preserved.

## Runtime architecture

ACHP separates durable collaboration identity from changing execution and source
state:

```text
Project Collaboration Root
    stable project identity, Route registry, shared constraints

Development Route Node
    long-lived goal/architecture route and route-owned continuity

Execution Endpoint
    replaceable engineer/agent/session/host capacity

Source Repository / Source State
    explicit repository, branch, commit, tree, worktree, Push/Pull evidence

Knowledge Plane
    Root-wide knowledge plus Route-owned scoped knowledge
```

Harness integrations are optional edges around these planes.

## Relay policy

The runtime decision is topology-first:

```text
one session
  -> no relay needed

multiple sessions, same host
  -> test same-host send capability only
     -> verified + target addressable: automatic
     -> otherwise: user manual relay

multiple sessions, multiple hosts
  -> test cross-host send capability
     -> verified + target addressable: automatic
     -> otherwise: user manual relay

unknown topology
  -> manual relay; do not block work
```

Never infer capability from the harness product name.

`unknown != verified`.

Read capability does not imply send capability.

Same-host send does not imply cross-host send.

## Knowledge model

`.agents/knowledge/` is deliberately lightweight.

Persist knowledge only when it is likely to change a future action and is meaningfully more expensive to rediscover than to maintain.

Recommended categories:

```text
guides/
decisions/
observations/
archive/
```

This model is compatible with a `self-evolution`-style knowledge lifecycle but does not require that Skill or any specific harness.

## Updating this Skill

With the recommended symlink installation:

```bash
cd ~/.local/share/agent-collaboration-setup
git pull
python3 scripts/install_skill.py --harness all --check
```

For copy-mode installations:

```bash
git pull
python3 scripts/install_skill.py --harness all --mode copy
```

Projects are **not** silently upgraded when the Skill repository changes. Upgrade a project intentionally:

```bash
python3 scripts/project_setup.py upgrade --root /path/to/project
```

This keeps setup changes reviewable.

## Publishing your fork/repository to GitHub

After editing the files:

```bash
git init
git add .
git commit -m "Add Project Collaboration Workspace and Route support"
git branch -M main
git remote add origin git@github.com:D1ChangGeng/Agent-collaboration.git
git push -u origin main
```

The public source repository is `D1ChangGeng/Agent-collaboration`; the
installable Skill slug and local discovery directory remain
`agent-collaboration-setup`.

## Validation and tests

Run:

```bash
python3 scripts/validate_skill.py
python3 -m unittest discover -s tests -v
```

The included GitHub Actions workflow runs both checks on pushes and pull requests.

## Development principles

1. Keep the Skill **setup-only**.
2. Keep the runtime protocol **harness-agnostic**.
3. Prefer open Agent Skills fields over harness-specific frontmatter.
4. Preserve existing project instructions and documentation.
5. Make adapters optional and removable.
6. Treat manual relay as a supported normal mode.
7. Keep machine/session capability observations out of Git.
8. Keep repository sync explicit in handoffs.
9. Avoid duplicating project truth into `.agents/knowledge/`.
10. Make upgrades intentional and reviewable.

## Repository map

```text
SKILL.md
README.md
README.zh-CN.md
CHANGELOG.md
CONTRIBUTING.md
LICENSE
scripts/
  install_skill.py
  project_setup.py
  workspace_setup.py
  validate_skill.py
assets/
  scaffold/
references/
  DESIGN.md
  HARNESS-COMPATIBILITY.md
  UPGRADE-POLICY.md
tests/
.github/
```

## Upstream references

- Agent Skills open specification: https://agentskills.io/
- Codex Skills: https://developers.openai.com/codex/build-skills
- Codex `AGENTS.md`: https://developers.openai.com/codex/agent-configuration/agents-md
- Claude Code Skills: https://code.claude.com/docs/en/skills
- Claude Code project memory / `AGENTS.md` compatibility: https://code.claude.com/docs/en/memory
- OpenCode Skills: https://opencode.ai/docs/skills/
- OpenCode instructions: https://opencode.ai/v2/docs/instructions
- Knowledge-design inspiration: https://github.com/D1ChangGeng/self-evolution

## License

MIT. Replace the license before publishing if you prefer a different open-source license.
