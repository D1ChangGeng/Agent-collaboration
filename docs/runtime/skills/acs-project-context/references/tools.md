# acs-project-context: tools

Use the actual exposed tools; retain returned handles instead of constructing internal routing identities.

- `read_profile`
- `list_projects`
- `load_project`
- `configure_root` (trusted Owner Client or bound Root manager within its Root)
- `list_routes`
- `list_collaborators`

Project identity and authorized contact scope; Native capacity and source files retain their own authorities.

Owner `load_project` reads current management documents from the selected
machine and can override `machine_id`/`management_path` for that read.
`configure_root` persists the authorized location and document paths and can
configure the Root manager in the same operation. No separate Project admission
operation is required. `configure_project` is a hidden compatibility call for
older clients.
Clearing or missing management files does not withdraw existing communication.

An unbound trusted Client has its own communication address and needs no
synthetic Slot. A bound Route manager or collaborator defaults to its Route
context; selecting another Route cannot broaden its authority. Check returned
completeness and follow-up reads when management files are absent or too large.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-tools.md); it is not the current communication contract.
