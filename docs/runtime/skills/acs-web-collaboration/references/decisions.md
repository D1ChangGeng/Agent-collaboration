# Web access decision map

Use the owner private Tunnel profile for the installation owner's stdio ACS
server when the client supports it. Keep the Tunnel in the intended owner's
Platform organization and ChatGPT workspace. Bind its ACS process to the trusted
owner credential. Use stable HTTPS with OAuth for a resource-server deployment.
The server checks the actual authenticated context and installed access mode.
See [the private Tunnel profile](../../../P2-PRIVATE-TUNNEL-PROFILE.md).

Account setup uses the owner's account browser on the selected client device.
Verify browser capability and account/workspace context before configuration.
Login, secret entry and connection consent remain owner account actions.

Use load_project for the current Project/Root/Route context and active work.
In owner mode, use the saved management machine/path or select machine_id and
management_path for one read. Follow read_file actions for documents beyond the
inline budget. An owner Project with an empty Source catalog can load its
management instructions and knowledge through this path.

Use configure_project with the expected Project revision when the saved
management location or document paths change. Set, replace or clear the
location; changes.management: null clears it. Read back the resulting revision,
observed document paths and context completeness.

Choose ACS machine tools for current files under the selected OS account.
Choose an available native, Git or repository provider reader for the source
version needed by the task. Record the actual commit/tree and relevant workspace
state. Owner source_baseline may be omitted or null; an eligible revise_work
can select, change or clear the work version.

Choose a historical Source reader when the task needs captured bytes. Select
source_id and revision explicitly, or source_id with base_revision and
target_revision for read_diff. Shared deployments use their original Source
catalog, permissions and version checks.

For Review and acceptance, inspect the exact candidate and report its actual
commit/tree through source_readback. Preserve consistency with recorded Evidence
and execution receipts, Reviewer independence and Finalizer authorization.

Use current native capability to decide execution, attached Session control and
immediate notifications. A lost client connection leaves durable Inbox and
response tracking available; reconnect and check_inbox through the actual
Session.

Remote TLS, keys, Node identity and replay checks remain effective in owner
mode. OAuth token expiry belongs to the resource-server credential boundary.
Existing unspecified access_mode configuration retains shared semantics until
explicit migration.
