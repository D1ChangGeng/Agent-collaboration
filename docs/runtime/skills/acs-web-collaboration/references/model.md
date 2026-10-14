# Web collaboration model

A web Agent connects to one ACS remote MCP endpoint through HTTPS or an admitted
secure Tunnel. The private owner Tunnel binds the local ACS process to the
installation owner's trusted credential and service context. An OAuth resource
server validates its token, subject and deployment rules.

The web Session selects project_id explicitly and loads ProjectContextPack.
In owner mode, load_project combines durable Project/Root identity, Route
summaries and active WorkItems with current instructions and knowledge indexes
from the selected machine's management directory. A saved management location
or a single call's machine_id/management_path selects that directory. An owner
Project with an empty Source catalog can load its current management files.

The context reports the actual management machine/path, observed document paths
and times, inline content hashes, completeness and missing context. Documents
beyond the inline budget provide read_file follow-ups. File pagination retains
the original machine, directory and path. Active work comes from Runtime
records and has its own list_work follow-up when the context budget is exceeded.

configure_project sets, replaces or clears the saved management location and
instruction/knowledge index paths using the current Project revision. Set
changes.management to null to clear the saved location. Management paths follow
the selected machine's OS namespace; location changes preserve Project and
Root identity.

Owner machine file tools operate on current ordinary files under the selected
OS account through Local, SSH or Node. read_file requires path. Each MCP
connection retains its machine and directory selection; filesystem_context
reports actual account/home/cwd and select_filesystem sets that default.
Optional machine_id/cwd selects one call's target. OS permissions govern access.

Agents choose an available native, Git, machine or repository provider reader
for the source version appropriate to their work, then record the actual
location, commit/tree and relevant workspace state. Owner WorkItem
source_baseline may be omitted or null. An eligible revise_work can select,
change or clear that version.

Recorded Source views form a historical archive. list_sources discovers
recorded identities; read_source, read_source_file, list_source_files and
search_source_files select both source_id and revision. read_diff selects
source_id, base_revision and target_revision. Archive pagination retains the
captured view_revision and source identity. Shared mode retains its existing
Source catalog, permissions, version and context checks.

Web Sessions perform management, architecture, Review, Specialist or Finalizer
duties through the actual advertised tools. Review and acceptance report the
candidate commit/tree actually inspected and compare it with exact candidate
Evidence and authenticated execution receipts. Reviewer independence and
Finalizer authorization remain part of acceptance. Owner admission follows
trusted identity, active objects, explicit revocation, deduplication and
revisions; shared deployments also apply their configured Grants, Policy and
Profiles. Execution depends on actual native capacity and readiness.

Notifications use the active MCP Connection and Session binding. Push or wake
requires the actual client capability. Durable Inbox, response and subscription
state remains available to a later authenticated Session.
