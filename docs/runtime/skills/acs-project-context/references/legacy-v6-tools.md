# Project context tool map

- read_profile returns trusted identity, tenant, access mode, client Profiles
  and connection state.
- list_projects discovers active Project IDs and Root handles visible to that
  authenticated context.
- load_project returns ProjectContextPack for root_management,
  route_management, reviewer or finalizer views.
- list_routes and list_work discover stable handles and current revisions.
- list_activity reads recorded event lineage.
- read_resource reads a known typed handle; the active schema determines
  supported revision selection.

Use list operations for discovery and read_resource for detail. Project
follow-ups carry project_id. Context-dependent mutations use the applicable
expected revisions from these reads and a stable client_request_id.

Context packs report completeness and source identity. In owner mode, a
current workspace view can include admitted tracked changes and untracked
files. Keep its view revision alongside the repository commit and tree; a
named fixed revision preserves the source used by an existing candidate.
