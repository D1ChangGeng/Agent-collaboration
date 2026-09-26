# Web collaboration model

A web SaaS Agent connects to one ACS remote MCP endpoint through HTTPS or an
admitted secure Tunnel and authenticates with OAuth. The Session has no trusted
local cwd. It discovers Project IDs, loads ProjectContextPack and uses logical
SourceBinding paths.

ProjectContextPack contains Root identity, instruction manifests, Route
summaries, knowledge indexes, SourceBindings, active work, Policy and
completeness. Content is inline within bounds or referenced by Artifact and
read_file follow-up.

Web Sessions can act as Root Manager, Architect, Reviewer, Specialist or
Finalizer under the corresponding Profile. Local execution and protected source
writes require admitted Runtime or Source-write capacity.
