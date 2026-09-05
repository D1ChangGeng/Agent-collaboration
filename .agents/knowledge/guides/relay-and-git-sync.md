---
kind: guide
status: active
scope:
  - ".agents/protocol/CAPABILITIES.md"
  - ".agents/protocol/RELAY.md"
  - ".agents/protocol/GIT-SYNC.md"
  - "assets/scaffold/.agents/protocol/CAPABILITIES.md"
  - "assets/scaffold/.agents/protocol/RELAY.md"
  - "assets/scaffold/.agents/protocol/GIT-SYNC.md"
use_when:
  - "choosing a transport for a session handoff"
  - "writing or reviewing a Relay Envelope"
  - "handing repository changes to another clone or host"
review_when:
  - "relay capabilities, topology, or handoff state names change"
---

# Topology first

First establish whether the task is single-session, same-host multi-session,
multi-host, or unknown. Then verify only the send capability required by that
topology. Do not infer capability from Codex, Claude Code, OpenCode, or any other
Harness name.

Manual user forwarding is a first-class transport. Automatic relay is allowed
only when the exact send capability is positively verified and the destination is
addressable. `unknown` is not `verified`; read/discovery does not imply send;
same-host send does not imply cross-host send; capability may be directional.

# Two independent state planes

Message relay and repository synchronization are separate. A delivered message
does not imply that a receiver has fetched or pulled the repository. Any handoff
involving repository changes must state branch, base/head commit, working-tree
state, Push result, and the receiver action (`none`, `fetch`, `pull-required`, or
`manual-resolution-required`).

The durable bridge for code and documentation is Git: modify, verify, capture
knowledge when justified, commit, push when authorized, and hand off the exact
baseline.

# Safety boundary

Never resolve divergence with destructive reset or clean operations by default.
Preserve uncommitted work and report unsafe or diverged state for explicit
resolution.

# Evidence

The protocol contracts and envelope are defined in the scoped files above. The
root `AGENTS.md` repeats only the high-signal routing rules and points to those
authoritative documents.
