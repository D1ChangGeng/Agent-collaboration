# Web collaboration tool map

- read_profile confirms trusted identity, tenant, access_mode, client views and
  connection state.
- list_projects discovers active project_id values.
- load_project hydrates Root, Route, instruction and Source context.
- filesystem_context discovers the actual machine, OS account, home, cwd and
  connected choices; select_filesystem sets this MCP connection's default.
- Owner read_file requires path and reads current account files. list_directory,
  glob and grep discover or search them; write_file, edit_file and apply_patch
  change them through Local, SSH or Node.
- list_sources reports Project repository/location/version guidance and Source
  provider capabilities.
- read_source_file, list_source_files and search_source_files read a selected
  Project Source view; revision selects captured bytes. read_source reports
  actual repository state and read_diff compares explicit captured versions.
- Shared mode retains the existing Source read_file/list_files/search_files
  catalog and its configured access checks.
- check_inbox and read_message recover durable collaboration state.
- list_evidence, list_reviews and submit_review support remote Review.
- send_message and wait_for_response retain the same response handles across
  immediate returns, synchronous waits and later reconnection.

A changed custom MCP schema can require metadata refresh in the existing
ChatGPT Plugins connection. Select Refresh, inspect the updated metadata, then
start a new conversation and rerun affected calls. See the
[official refresh procedure](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata).
The owner server exposes optional chosen deadline, create_work budget and wait
timeout; an existing client's refreshed schema establishes the input it sees.

Every Project tool supplies project_id. Owner Project mutations use stable
request identity and expected revisions; an explicit business deadline is optional.
Sync waiting uses an optional caller timeout, while durable tracking continues.

Machine file calls supply the file action and optional machine_id/cwd. Each
connection retains its selection; an individual override applies to one call.
Core supplies authenticated connection and internal request data. Pagination
continues on the cursor's original machine, directory, path and query.

MCP instructions expose the minimal startup rule. Skill metadata routes the
current question to its knowledge module; one named reference supplies further
detail. Notifications follow the actual Connection and Session capability,
and the Project Inbox provides durable recovery.
