# Web access decision map

Use the single-user private Tunnel profile for an installation owner's Linux
stdio ACS server when the Host supports it. Keep the Tunnel in that owner's
Platform organization and ChatGPT workspace, and keep its ACS credential bound
to one existing Grant. Use stable HTTPS with OAuth for a shared or hosted
resource server. In both paths, server-side Domain checks are authoritative.
See [the private Tunnel profile](../../../P2-PRIVATE-TUNNEL-PROFILE.md).

Account setup uses the installation owner's external browser on their client
device. Select external browser control only after verifying that capability
and the intended account/workspace context. Otherwise supply official links,
page locations, actions, expected results and the next step for the owner to
complete. Required login, secret entry, permission approval and connection
consent remain owner actions. Public documentation retrieval is a separate
read-only activity; embedded Harness browser availability does not establish
access to the owner's account browser.

Use ACS filesystem tools for local Management Root, dirty state and Node-bound
Evidence. Use official GitHub MCP or another repository provider for remote
commits and review context. With both paths, compare exact commit and tree.

When native push wake is unavailable, retain notification in Project Inbox for
the next authorized Session. Capability observations decide the path.
