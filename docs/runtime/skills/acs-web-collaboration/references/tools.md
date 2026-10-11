# Web collaboration tool map

- read_profile confirms trusted identity, tenant, access_mode, client views and
  connection state.
- list_projects discovers active project_id values.
- load_project hydrates Root, Route, instruction and Source context.
- list_sources selects admitted filesystem or external repository access.
- list_files, search_files, read_file, read_source and read_diff provide bounded
  current workspace or fixed revision reads through the SourceBinding.
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

Every Project tool supplies project_id. Owner mutations use stable request
identity and expected revisions; an explicit business deadline is optional.
Sync waiting uses an optional caller timeout, while durable tracking continues.

MCP instructions expose the minimal startup rule. Skill metadata routes the
current question to its knowledge module; one named reference supplies further
detail. Notifications follow the actual Connection and Session capability,
and the Project Inbox provides durable recovery.
