# Project context tool map

- read_profile returns trusted identity, tenant, access mode, client Profiles
  and connection state.
- list_projects discovers active Project IDs and Root handles visible to that
  authenticated context.
- Owner load_project reads current management files for root_management,
  route_management, reviewer or finalizer views. Optional machine_id and
  management_path select that call's location.
- Owner configure_project accepts project_id, client_request_id,
  expected_revision and changes for management and document paths.
- list_routes and list_work discover stable handles and current revisions.
- list_activity reads recorded event lineage.
- read_resource reads a known typed handle; the active schema determines
  supported revision selection.
- read_file resolves current document follow-ups using machine_id, cwd and path.

Use list operations for discovery and read_resource for detail. Project
follow-ups carry project_id. Context-dependent mutations use the applicable
expected revisions from these reads and a stable client_request_id.

For configure_project, management has mode=current_files, machine_id and path;
management=null clears the saved location. instruction_paths and
knowledge_index_paths select documents relative to that directory. Read back
the Project revision, management_root and context completeness after changes.
Inline document entries identify their path, observation time, content and hash;
partial context identifies missing paths and ordinary read_file follow-ups.

Owner create_work accepts omitted or null source_baseline. Eligible revise_work
can choose, replace or clear that selection. Recorded Source history is selected
by explicit source_id/revision; current file operations use machine tools.
Shared context and Source inputs retain their original contract. Read exact
schemas from the active installed catalog.
