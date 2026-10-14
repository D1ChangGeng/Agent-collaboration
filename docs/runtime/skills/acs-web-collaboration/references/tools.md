# Web collaboration tool map

- read_profile confirms trusted identity, tenant, access_mode, client views and
  connection state.
- list_projects discovers active project_id values.
- Owner load_project reads current Root/Route instructions and knowledge indexes
  from the saved management machine/path or optional machine_id/management_path
  for one call, and includes active work and context completeness. Documents
  beyond the inline budget provide read_file follow-ups.
- Owner configure_project uses client_request_id, project_id, expected_revision
  and changes to set, replace or clear management, instruction_paths and
  knowledge_index_paths. changes.management: null clears the saved location.
- filesystem_context discovers the actual machine, OS account, home, cwd and
  connected choices; select_filesystem sets this MCP connection's default.
- Owner read_file requires path and reads current account files. list_directory,
  glob and grep discover or search them; write_file, edit_file and apply_patch
  change them through Local, SSH or Node.
- list_sources discovers recorded Source identities, captured versions and
  provider capabilities.
- Historical read_source, read_source_file, list_source_files and
  search_source_files select explicit source_id and revision. read_diff selects
  source_id, base_revision and target_revision for its two captured versions.
- Shared mode retains the existing Source read_file/list_files/search_files
  catalog and its configured access checks.
- Owner create_work accepts omitted or null source_baseline; eligible
  revise_work changes select, replace or clear the Agent's work version.
- list_evidence and list_reviews expose the recorded candidate evidence and
  decisions. submit_review and accept_work report the inspected
  source_readback.commit and source_readback.tree, with exact candidate/Evidence
  consistency and independent Reviewer and Finalizer authorization.
- check_inbox and read_message recover durable collaboration state.
- send_message and wait_for_response retain the same response handles across
  immediate returns, synchronous waits and later reconnection.

A changed custom MCP schema can require metadata refresh in the existing
ChatGPT Plugins connection. Select Refresh, inspect the updated metadata, then
start a new conversation and rerun affected calls. See the
[official refresh procedure](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata).
The owner server exposes optional chosen deadline, create_work budget and
source_baseline, load_project machine/location selection, and wait timeout;
an existing client's refreshed schema establishes the input it sees.

Every Project tool supplies project_id. Owner Project mutations use stable
request identity and expected revisions; an explicit business deadline is optional.
Sync waiting uses an optional caller timeout, while durable tracking continues.

Machine file calls supply the file action and optional machine_id/cwd. Each
connection retains its selection; an individual override applies to one call.
Core supplies authenticated connection and internal request data. Pagination
continues on the cursor's original machine, directory, path and query.
Current management file context also works for an owner Project whose recorded
Source catalog is empty. Shared context uses its advertised Source contract.

MCP instructions expose the minimal startup rule. Skill metadata routes the
current question to its knowledge module; one named reference supplies further
detail. Notifications follow the actual Connection and Session capability,
and the Project Inbox provides durable recovery.
