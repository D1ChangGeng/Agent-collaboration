# acs-project-context: tools

Use the actual exposed tools; retain returned handles instead of constructing internal routing identities.

- `list_projects`
- `load_project`
- `configure_project` (authorized Owner project managers)
- `list_routes`
- `list_collaborators`

Project identity and authorized contact scope; Native capacity and source files retain their own authorities.

Owner `load_project` reads current management documents from the selected
machine and can override `machine_id`/`management_path` for that read.
`configure_project` persists the authorized location and document paths.
Clearing or missing management files does not withdraw existing communication.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-tools.md); it is not the current communication contract.
