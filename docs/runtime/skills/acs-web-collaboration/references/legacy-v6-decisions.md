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

Use load_project for the current Project context. Choose ACS filesystem tools
for the current admitted workspace, Management Root and Node Evidence. Choose
the external repository provider for remote commits and Review context. Keep
workspace view identity separate from Git commit and tree.

Use current native capability to decide execution, attached Session control and
immediate notifications. A lost client connection leaves durable Inbox and
response tracking available; reconnect and check_inbox through the actual
Session.

Remote TLS, keys, Node identity and replay checks remain effective in owner
mode. OAuth token expiry belongs to the resource-server credential boundary.
Existing unspecified access_mode configuration retains shared semantics until
explicit migration.
