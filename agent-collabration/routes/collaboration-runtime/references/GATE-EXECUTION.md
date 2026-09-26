# Runtime Gate execution references

P1 evidence execution uses `tools/runtime/gate_runner.py` and the schemas under
`docs/runtime/`. Probe commands run only through the verified Linux bubblewrap
sandbox against an exact read-only Git snapshot and a separate output mount.
Windows has no admitted sandbox and therefore remains NOT_RUN.

P2 preparation uses `tools/runtime/p2_harness.py` and
`docs/runtime/P2-INVENTORY-TEMPLATE.json`. The template binds stable Machine
identities only. Initialization reobserves the current local Machine and Git
commit/tree; execution must independently reobserve the remote Machine. Gate
order is P1, P2-CODEX, then P2-OPENCODE. The checked-in tools and documents do
not contain a PASS Gate or authorize fault injection.
