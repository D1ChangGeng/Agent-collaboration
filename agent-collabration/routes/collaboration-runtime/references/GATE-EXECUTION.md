# Runtime Gate execution references

P1 evidence execution uses `tools/runtime/gate_runner.py` and the schemas under
`docs/runtime/`. Probe commands run only through the verified Linux bubblewrap
sandbox against an exact read-only Git snapshot and a separate output mount.
Windows has no admitted sandbox and therefore remains NOT_RUN.

P2 preparation uses `tools/runtime/p2_harness.py` and
`docs/runtime/P2-INVENTORY-TEMPLATE.json`. The template binds stable Machine
identities only; its `not_run` values do not report completed execution state.
Historical reviewed Gate results, later candidate continuity and the current
Control Parity result are indexed in `docs/runtime/P2-EXECUTION-STATUS.md`.
Initialization reobserves the current local Machine and Git commit/tree;
execution must independently reobserve the remote Machine. Gate order is P1,
P2-CODEX, P2-OPENCODE, P2-MCP-WORKFLOW, P2-MANAGEMENT-WORKFLOW,
P2-CONTROL-PARITY, then P2-REVIEW. The public collaboration and management
surfaces are defined in docs/runtime/P2-MCP-WORKFLOW-CONTRACT.md and
docs/runtime/P2-MANAGEMENT-WORKFLOW-CONTRACT.md at surface revision
acs-p2-mcp-workflow/6. The Gates validate Profile-filtered discovery, explicit
project context, closed schemas, discriminated results, executable follow-ups,
Source reads, metadata-first Skill routing and selective references. The
evidence index distinguishes historical runs, current-candidate continuity,
and the final P2 review boundary.

Independent review follows a capability-first order. Reviewers inspect the
Runtime implementation and architecture, then verify representative product
behavior through direct receipts, fault injection, read-back and postflight
cleanup. Structural validity, expiry, source binding, reviewer identity and
authorization are hard prerequisites for passage; they do not substitute for
live Runtime behavior. Component-only, fixture-only, no-model,
single-normal-delivery and offline-validator results retain their declared
scope. Identity continuity, Harness replacement and integrated acceptance are
promoted only from the live layers named by their scenario contracts.
