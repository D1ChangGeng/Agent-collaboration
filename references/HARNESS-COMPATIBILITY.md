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

## Native Runtime environment

New single-owner installations select access_mode=owner. Native Codex and
OpenCode Drivers use the chosen user's environment, tools, MCP servers,
plugins, project configuration, provider, models and approval configuration.
Codex loads the selected approval_policy. Driver server_request_handler can
answer native approval or information requests through JsonRpcClient.
Standard headless Receiver factory leaves that hook unconfigured and replies
-32601 through the transport. Interactive capability is established by the
installed client interface, actual handler and decision/response readback.
Current binary/configuration observations are resolved at preparation time;
the installed native API determines exact Session read, send and cancel
capability. Process termination requires confirmed ownership of that process
or containment.

Owner registrations persist while execution readiness is inspected at use.
API-oriented integrations retain their version and capability checks.
Shared/reference Profiles keep their configured isolation, restricted
settings, version pins and time windows. Recorded conformance and Gate runs
retain those original bindings.

See [Owner Runtime](../docs/runtime/OWNER-RUNTIME.md) for admission, lifetime,
current workspace and migration semantics. Skill discovery paths establish
installation placement; actual native readback establishes operational
capability. Existing Receiver process profiles retain their separately signed
mode. Receiver owner/native migration computes matching factory/configuration
digests, re-signs the next Endpoint revision with the original Node key, commits
it and restarts with actual mode and Session readback. Credential, keys, Node
identity and revocation state retain their identities.

## Runtime capability warning

The following MUST NOT be inferred from this table:
- ability to discover another session;
- ability to read another session;
- ability to send to another session;
- ability to reach another machine;
- ability to Push/Pull a Git remote.

Those are runtime capabilities and must be observed separately.
