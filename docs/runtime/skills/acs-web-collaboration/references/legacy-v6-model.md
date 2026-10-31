# Web collaboration model

A web Agent connects to one ACS remote MCP endpoint through HTTPS or an admitted
secure Tunnel. The private owner Tunnel binds the local ACS process to the
installation owner's trusted credential and service context. An OAuth resource
server validates its token, subject and deployment rules.

The web Session selects project_id explicitly and loads ProjectContextPack.
The pack carries Root identity, instruction manifests, Route summaries,
knowledge indexes, SourceBindings, active work and completeness. Source
context includes exact commit or workspace view revisions. Content is inline
within bounds or referenced by verified Artifact and an owner read_source_file
follow-up. Shared clients use their advertised Source reader.

Web Sessions perform management, architecture, Review, Specialist or Finalizer
duties through the actual advertised tools. Owner admission follows trusted
identity, active objects, explicit revocation, deduplication and revisions;
shared deployments also apply their configured Grants, Policy and Profiles.
Execution depends on actual native capacity and readiness.

Notifications use the active MCP Connection and Session binding. Push or wake
requires the actual client capability. Durable Inbox, response and subscription
state remains available to a later authenticated Session.

Owner machine file tools operate on current ordinary files under the selected
OS account through Local, SSH or Node. read_file requires path. Each MCP
connection retains its machine and directory selection; filesystem_context
reports actual account/home/cwd and select_filesystem sets that default.
Optional machine_id/cwd selects one call's target. OS permissions govern access.

SourceBinding supplies repository, location and version guidance. Explicit
read_source_file/list_source_files/search_source_files, read_source and read_diff
use Project Source views and captured versions through the selected provider's
admitted access. Current owner Source views can include local edits and admitted
untracked files; named snapshots retain exact source for Review. Shared mode
retains its existing Source catalog, permissions and version checks.
