# P2 project management and web collaboration contract

Status: adopted P2 design contract. MCP surface revision:
acs-p2-mcp-workflow/4.

This contract defines how external Agent sessions manage one or more ACS
projects from local Harnesses and web SaaS clients. The machine-readable tool
catalog is [p2-mcp-tool-contract.json](p2-mcp-tool-contract.json). Collaboration
delivery and continuation behavior is defined in
[P2-MCP-WORKFLOW-CONTRACT.md](P2-MCP-WORKFLOW-CONTRACT.md).

## Root Agent model

Root Agent is a runtime role projection:

~~~text
authenticated external Agent Session
+ explicit project_id
+ Project Collaboration Root context
+ active management Grant
~~~

Project, Collaboration Root, Route, Scope, AgentSlot, WorkItem and accepted
state are durable identities. Root Agent is the current external reasoning
session acting with management authority. Concurrent Codex, Claude Code,
OpenCode and web sessions can therefore act as Root Agents without a persistent
RootAgent domain object.

ACS records authenticated subject, command lineage, Session binding, delivery
address and notification subscription. Revision checks, Grants, Claims and
Leases coordinate concurrent decisions. A replacement Session can recover the
same Project, Route, WorkItem and Inbox state.

## Installation and project adoption

ACS is installed once per user, machine fleet or hosted tenant. The global
installation owns the Runtime service, MCP endpoints, local Node, Harness
configuration, remote HTTPS or Tunnel connection and authentication support.

Each project is adopted once. Project adoption:

1. creates or preserves a stable project_id;
2. records it in the Management Root AGENTS managed block;
3. stores the machine-readable value in .agents/manifest.json;
4. records Root and Route identities;
5. registers SourceBindings and ProjectContextManifest paths;
6. validates that list_projects returns the adopted project.

The manifest is the machine identity authority. AGENTS presents the same ID to
local Harness sessions. A mismatch blocks project mutations until project
validation restores one value.

Project adoption belongs to the setup Skill and installer API. Runtime Root
Agent tools begin after adoption.

## Explicit project context

read_profile, list_projects and list_connections are global tools. Every other
public tool requires project_id. Handle-based tools also validate that the
handle belongs to the supplied project.

Local Harnesses obtain project_id from AGENTS and the manifest. Web clients call
list_projects and then load_project. Tool results and follow-up calls repeat
project_id so later calls preserve the boundary.

## ProjectContextPack

load_project is the context-hydration entry for Root Manager, Route Manager,
Reviewer and Finalizer sessions.

Input:

~~~json
{
  "project_id": "project-agent-collaboration",
  "context_view": "root_management",
  "include": [
    "root",
    "routes",
    "instructions",
    "knowledge_indexes",
    "source_bindings",
    "active_work",
    "policies"
  ],
  "at_revision": null,
  "max_inline_bytes": 65536
}
~~~

context_view is one of root_management, route_management, reviewer or finalizer.
The result contains:

- Project and Root identity;
- Management Root SourceBinding and logical path;
- AGENTS and Route instruction manifests with revision and digest;
- Route summaries and lifecycle revisions;
- knowledge indexes and decision references;
- SourceBindings and access modes;
- active WorkItem, Review and unresolved-item summaries;
- relevant policy and Grant summaries;
- context_completeness and missing_context;
- exact follow-up tools and arguments.

Instruction content is inlined within max_inline_bytes. Larger content returns
an immutable Artifact reference or read_file follow-up. Provider paths are
logical SourceBinding paths; web clients do not need operating-system absolute
paths.

A context pack reports current, partial or stale completeness. The Agent binds
claims to the reported source and observation revisions.

## Web and local source access

A SourceBinding identifies a source authority and its admitted capabilities.
Supported read paths include:

- local Node filesystem;
- Git repository or hosted workspace;
- official GitHub MCP used by the Agent alongside ACS;
- immutable Artifact references.

ACS filesystem tools are list_sources, list_files, search_files, read_file,
read_source and read_diff. They operate only below an authorized SourceBinding,
at an explicit source revision, with bounded output.

When GitHub MCP is selected, load_project returns repository identity, exact
revision and required context paths. The bundled Skill coordinates ACS state
with GitHub reads. ACS retains project identity, WorkItem lineage, source
readback and synchronization evidence; GitHub remains the source authority.

When both local and GitHub paths are available, read_source compares commit,
tree, push state and receiver synchronization. Message delivery and source
synchronization remain independent.

Optional Source write tools are apply_patch, create_branch, commit_changes and
push_changes. They require a Source-write Profile, WorkItem lineage, exact
precondition and protected-boundary readback.

## Tool profiles

The server filters tools/list by authenticated Grant and active Profile.

### Root Manager

Root Manager receives global discovery, project context, project lists, project
reads, Source reads, management actions and continuation tools.

### Route Manager

Route Manager receives project context, Route-scoped lists and reads, team and
WorkItem management, messaging, review requests and continuation tools.

### Reviewer

Reviewer receives project context, lists, Source reads, evidence and Review
reads, submit_review and bounded subscription tools. Review independence is
verified from identity, assignment and candidate lineage.

### Engineer

Engineer receives project context, assigned WorkItems, Source read and admitted
Source write tools, messaging and response continuation.

### Operator

Operator receives identity and connection reads plus submit_command. The run
compatibility alias maps to the same advanced Domain command contract.

## Management list tools

All enumeration operations use list in the tool name.

| Tool | Result |
|---|---|
| list_projects | Project IDs, Root handles and lifecycle summaries |
| list_connections | Node, Tunnel, Source Provider and remote MCP connections |
| list_routes | registered development lines and source summaries |
| list_work | WorkItem execution, review, acceptance and blocker summaries |
| list_collaborators | AgentSlot, role, assignment and Session activity |
| list_harnesses | eligible Harness capacities and expiry evidence |
| list_sources | SourceBindings, revisions and admitted capabilities |
| list_activity | Domain event lineage and revisions |
| list_evidence | Evidence and Artifact handles |
| list_reviews | Review assignments, decisions and unresolved summaries |
| list_files | SourceBinding directory entries |

List tools accept closed filters, cursor and limit. Each item includes its stable
handle, revision, evidence class and exact detail-read call.

## Detail reads

read_resource reads one known Project, Route, WorkItem, Evidence, Artifact or
AcceptedState handle. It is a pure read.

~~~json
{
  "project_id": "project-agent-collaboration",
  "handle": "route:authority-01:project-agent-collaboration:runtime",
  "view": "detail",
  "at_revision": 12,
  "include": ["source_state", "work_summary", "relations"],
  "cursor": null,
  "limit": 50,
  "content_mode": "reference",
  "max_inline_bytes": 16384
}
~~~

Views are summary, detail, content, history and evidence. Each resource kind
publishes a closed include vocabulary and available_views. content_mode is
inline or reference. Bounded content returns an Artifact handle when it exceeds
the inline limit.

read_message accepts Message and response handles. Its consume parameter
defaults to true and records owner consumption in the same transaction. This
separates collaboration-message observation from generic resource reads.

check_inbox lists Messages, responses, review requests and recovery
notifications for a project management or AgentSlot context. Reading an item
uses read_message.

## Management actions

create_route and update_route own Route lifecycle changes.

configure_team replaces the earlier broad collaboration-setup name. It operates
inside an existing Scope and creates or revises AgentSlot, role, Grant, Policy
and budget bindings.

Input:

~~~json
{
  "client_request_id": "configure-runtime-review-team-01",
  "project_id": "project-agent-collaboration",
  "scope_handle": "scope:route-runtime",
  "expected_revision": 4,
  "members": [
    {
      "agent_slot_id": "runtime-reviewer",
      "role": "reviewer",
      "grant_ref": "grant:runtime-reviewer",
      "budget_ref": "budget:runtime-reviewer",
      "harness_requirements": ["codex", "opencode"]
    }
  ],
  "policies": ["policy:runtime-review/3"],
  "budgets": ["budget:runtime-reviewer"],
  "deadline": "2026-09-22T16:00:00Z"
}
~~~

create_work and revise_work own WorkItem intent and revision.

handoff_work transfers existing responsibility with exact source state,
context, evidence, unresolved items and acknowledgement policy.

request_review creates a Review bound to candidate, source baseline, criteria
and evidence requirements. submit_review records a reviewer decision and
findings. accept_work commits accepted state at the Finalizer or product-owner
authorization boundary.

## Messaging and continuation

send_message requires project_id and an existing WorkItem handle. It atomically
commits the Message, Outbox entry, response expectation and completion
notification. Async is the default. Sync adds one bounded wait on the same
response handle.

watch_changes creates durable subscriptions for Project, Route, WorkItem,
Review, Source and recovery events. The initiating Session receives an immediate
wake when its Harness supports it. The Project management Inbox retains the
notification for later authorized sessions.

wait_for_response performs bounded any or all observation. set_notification
changes subscription delivery. cancel_work ends the WorkItem objective.
stop_attempt controls one concrete Runtime Attempt.

The default delivery policy is queue_until_idle. Current Session activity is an
expiring Driver or Node observation. Idle admits invocation, busy retains an
Inbox item until idle, offline retains it for a current binding, and unknown
waits for a fresh observation.

## Remote web MCP

A web SaaS client connects to one global ACS remote MCP endpoint and then uses
list_projects and load_project. The remote path uses Streamable HTTP over HTTPS
or a supported secure tunnel, OAuth-protected resource metadata and per-tool
security scopes.

The installer configures the ACS endpoint, authorization metadata and local
Tunnel client. The user completes the SaaS account connection and OAuth consent.
The exact callback value shown by the SaaS management page is admitted by the
authorization server.

Official ChatGPT references used by this contract:

- https://developers.openai.com/plugins/deploy/connect-chatgpt?site_locale=en
- https://developers.openai.com/plugins/build/auth?site_locale=en
- https://developers.openai.com/plugins/concepts/skills?site_locale=en

## Storage boundary

ACS stores project identity, topology, Grants, WorkItems, Attempts, Message and
receipt state, subscriptions, Evidence metadata, AcceptedState and source
readback. Artifact bytes use the configured Artifact authority. Source content
remains in the filesystem or repository provider. Harness transcripts and model
context remain Harness-owned. Secret values remain in their secret authority.

## Acceptance

P2-MANAGEMENT-WORKFLOW executes after P2-MCP-WORKFLOW. Direct evidence covers:

- global installation and project adoption identity;
- local and web ProjectContextPack hydration;
- explicit project isolation;
- cross-project listing;
- Route, WorkItem, collaborator, evidence and Review lists;
- filesystem SourceBinding reads;
- GitHub-assisted context loading when that provider is admitted;
- stale context and source mismatch handling;
- web Reviewer and Root Manager flows;
- subscriptions and Project Inbox recovery;
- Skill-driven workflows with one-sentence user entry.