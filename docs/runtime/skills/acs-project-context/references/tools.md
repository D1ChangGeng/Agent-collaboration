# Project context tool map

- read_profile returns authenticated subject, tenant, Profiles and connection state.
- list_projects discovers Project IDs and Root handles.
- load_project returns ProjectContextPack for root_management,
  route_management, reviewer or finalizer views.
- list_routes and list_work discover stable handles and revisions.
- list_activity exposes event lineage without making chat history authoritative.
- read_resource reads one known typed handle at an exact revision.

Use list operations for discovery and read_resource for detail. Tool follow-ups
carry project_id. Context-dependent mutations use the latest applicable
revision from these reads.
