# Project Collaboration Workspace `.agents/`

This is the control-plane state for a Project Collaboration Root.

The primary layout nests the Management Root in the Project Git Repository /
Source Checkout Root. Management documents, knowledge, and Route directories
are tracked with product code. Each host uses its own clone with the same
repository-relative layout and explicit Git synchronization. The Source
Checkout Root's `.gitignore` holds scoped rules for transient files and secrets;
the nested Management Root has no child `.gitignore`. Standalone workspaces
remain a compatibility deployment.

- `coordination/ROOT.md` and `ROOT-BASELINE.md` define Root responsibilities and
  the migration contract.
- `coordination/routes.yaml` is the stable Route registry; it is not a per-turn
  status log.
- `protocol/` defines transport, repository-sync, knowledge, and source-state
  boundaries.
- `knowledge/` holds only Root-owned durable knowledge. Route knowledge remains
  in each Route directory and is referenced by the registry.
- Harness/session context and capability observations stay local to the running
  environment; setup does not create or maintain a `runtime/` project surface.

The `agent-collaboration-setup` Skill initializes and validates this state but is
not required for normal collaboration after setup.
