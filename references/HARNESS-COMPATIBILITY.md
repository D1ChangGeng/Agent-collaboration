# Harness Compatibility

This document describes installation/discovery compatibility, not runtime capability guarantees.

Runtime relay capability must always be verified in the actual environment.

## Agent Skills format

`SKILL.md` uses only portable Agent Skills frontmatter:
- `name`
- `description`
- `license`
- `compatibility`
- `metadata`

No Claude-only invocation fields are required.

## Codex

Recommended personal Skill path:

```text
~/.agents/skills/agent-collaboration-setup/
```

Codex project collaboration runtime uses root/nested `AGENTS.md` discovery.

## OpenCode

OpenCode recognizes the Agent-compatible Skill path:

```text
~/.agents/skills/agent-collaboration-setup/
```

It also recognizes OpenCode-native and Claude-compatible locations, but this project prefers the shared Agent Skills path to reduce duplication.

Current OpenCode V2 persistent project instructions use `AGENTS.md`.

## Claude Code

Recommended personal Skill path:

```text
~/.claude/skills/agent-collaboration-setup/
```

Claude Code project persistent instructions use `CLAUDE.md`.

Claude Code officially supports:

```text
@AGENTS.md
```

inside `CLAUDE.md`, so ACHP installs only that compatibility route and keeps `AGENTS.md` canonical.

## Other Agent Skills clients

If a harness supports the open Agent Skills format, install the repository directory in that harness's Skill discovery path.

If the harness does not discover `AGENTS.md`, add the thinnest supported persistent-instruction route that instructs/imports the canonical root `AGENTS.md`.

Do not duplicate the ACHP protocol body merely to satisfy a harness convention.

## Runtime capability warning

The following MUST NOT be inferred from this table:
- ability to discover another session;
- ability to read another session;
- ability to send to another session;
- ability to reach another machine;
- ability to Push/Pull a Git remote.

Those are runtime capabilities and must be observed separately.
