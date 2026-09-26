# Web access decision map

Use secure Tunnel for private local ACS access when the client and deployment
support it. Use stable HTTPS for hosted or published service access. OAuth
metadata and per-tool scopes express requested access; server verification is
authoritative.

Use ACS filesystem tools for local Management Root, dirty state and Node-bound
Evidence. Use official GitHub MCP or another repository provider for remote
commits and review context. With both paths, compare exact commit and tree.

When native push wake is unavailable, retain notification in Project Inbox for
the next authorized Session. Capability observations decide the path.
