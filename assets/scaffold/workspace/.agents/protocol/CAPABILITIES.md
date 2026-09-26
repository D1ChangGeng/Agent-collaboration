# Capability Model

Capabilities are runtime facts, not Harness-brand assumptions. Keep discovery,
read, send, repository access, and source-state observation independent.

```text
session.discover.same_host
session.read.same_host
session.send.same_host
session.discover.cross_host
session.read.cross_host
session.send.cross_host
source_state.read
repository.fetch
repository.pull
repository.push
```

Represent each observation as `verified`, `unavailable`, or `unknown`, with host,
Harness, session, permission, and observed-at context kept in the current
Harness/session context. The Workspace does not require a persisted capability
record.
`unknown` is unavailable for safety. `--add-dir` or a workspace root does not
by itself prove AGENTS discovery or relay capability.
