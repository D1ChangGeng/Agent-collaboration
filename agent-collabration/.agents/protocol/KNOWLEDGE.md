# Knowledge Scope Boundary

The Collaboration system defines who owns a knowledge surface and how Root and
Route scopes are referenced. The installed `self-evolution` system defines how
knowledge is discovered, captured, corrected, indexed, and maintained.

Root `.agents/knowledge/` should contain only project-wide collaboration
invariants and adopted Root decisions. A Route keeps its own Guides, Decisions,
Observations, archive, and state. The Root registry points to those route-owned
surfaces; it does not copy or reimplement them.

Persist a claim only when it has future-action value, a clear scope, and
traceable evidence. Keep transient endpoint capabilities, credentials, raw logs,
and unverified implementation claims out of durable Root knowledge.
