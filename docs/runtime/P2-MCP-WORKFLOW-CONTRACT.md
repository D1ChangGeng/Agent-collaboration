# P2 MCP collaboration and continuation contract

Status: adopted P2 implementation contract. Surface revision:
acs-p2-mcp-workflow/5.

This contract defines the typed collaboration, messaging and continuation
surface. Project and web management behavior is defined by
[P2-MANAGEMENT-WORKFLOW-CONTRACT.md](P2-MANAGEMENT-WORKFLOW-CONTRACT.md). The
machine-readable catalog is
[p2-mcp-tool-contract.json](p2-mcp-tool-contract.json).

## Responsibility boundary

External Agents decide goals, team composition, task decomposition, review
strategy and the next intelligent action. ACS authenticates those decisions,
applies authorization and revision checks, persists collaboration state,
performs deterministic delivery and recovery, and returns evidence-bound
observations.

Root Agent is a runtime role created by an authenticated external Agent Session
acting on an explicit project_id with a management Grant. Durable identity
belongs to Project, Root, Route, Scope, AgentSlot, WorkItem and accepted state.

## Surface organization

The server filters tools/list by the caller's authenticated Profile.

| Group | Tools |
|---|---|
| Global | read_profile, list_projects, list_connections |
| Project context | load_project |
| Project lists | list_routes, list_work, list_collaborators, list_harnesses, list_sources, list_activity, list_evidence, list_reviews |
| Project reads | read_resource, read_message, check_inbox |
| Source reads | list_files, search_files, read_file, read_source, read_diff |
| Project actions | create_route, update_route, configure_team, create_work, revise_work, handoff_work, send_message, request_review, submit_review, accept_work |
| Continuation | watch_changes, wait_for_response, set_notification, cancel_work, stop_attempt |
| Optional Source writes | apply_patch, create_branch, commit_changes, push_changes |
| Advanced | submit_command |

Enumeration uses list names. Search is reserved for query operations. Canonical
tool names use two or three familiar words and align Agent intent, human
collaboration language and Domain behavior.

## Project context

read_profile, list_projects and list_connections are global. Every other public
tool requires project_id. A typed handle also carries project ownership, and ACS
validates it against the argument.

Local Harnesses read project_id from the Management Root AGENTS block and
machine manifest. Web clients call list_projects and load_project. Every result
and executable follow-up repeats project_id.

## MCP exposure

Each tools/list entry contains:

- canonical name and human title;
- selection-oriented description;
- closed inputSchema and outputSchema;
- readOnlyHint, destructiveHint, idempotentHint and openWorldHint;
- per-tool OAuth security scopes;
- result_type discriminator.

The MCP server instructions direct an Agent with missing or stale project
context to list_projects and load_project before project-scoped work.

## Result wire format

Every tool returns native MCP content, structuredContent and isError fields.
Success uses acs-mcp-result/3:

~~~json
{
  "schema_version": "acs-mcp-result/3",
  "result_type": "message_submission",
  "ok": true,
  "state": "accepted",
  "data": {},
  "follow_ups": [
    {
      "rel": "read_response",
      "tool": "read_message",
      "arguments": {
        "project_id": "project-agent-collaboration",
        "handle": "response:message-01",
        "consume": true
      }
    }
  ],
  "metadata": {
    "observed_at": "2026-09-22T15:30:00Z",
    "evidence_class": "authority_committed"
  }
}
~~~

result_type selects the exact data contract. Fields unrelated to that type are
absent. Each follow-up provides rel, canonical tool and complete arguments.

A rejected command or failed observation uses result_type problem, ok false, a
stable error code, retryability, details, conflict revision and recovery
follow-ups. MCP isError is true for that result.

## Authentication and mutation context

Tenant, Authority, subject and active Grant come from authenticated transport
or enrollment context. A project_id selects an authorized Project; it does not
grant access.

Every mutating tool requires client_request_id, an expected revision or exact
precondition, and an absolute deadline. Equivalent replay returns the committed
disposition. A changed canonical payload conflicts.

## Team configuration

configure_team operates inside an existing Scope. It creates or revises:

- AgentSlots;
- roles;
- Grants;
- Policies;
- budgets;
- Harness capability requirements.

It returns team_configuration with operation, team_handle, team_revision,
scope_handle and member_handles. list_collaborators and read_resource provide
readback.

## Work and handoff

create_work creates the durable WorkItem before delegation. revise_work preserves
prior revisions. handoff_work transfers existing responsibility and binds:

- exact source state;
- context and evidence handles;
- unresolved items;
- origin and destination AgentSlots;
- acknowledgement policy.

Message transport and Git synchronization remain independent. A handoff result
states branch, commit, tree, worktree, push state and receiver sync evidence.

## Messaging

send_message commits one addressed Message, durable Outbox entry, response
expectation and notification subscription.

Required arguments include:

- client_request_id and project_id;
- work_handle and expected_work_revision;
- target Scope and AgentSlot;
- goal, request and constraints;
- accepted revision and required evidence;
- deadline.

Defaults:

~~~text
activation=invoke
delivery_policy=queue_until_idle
expect_response=true
response_mode=async
wait_until=response_received
~~~

Async returns after Authority commit and leaves the initiating Agent free to
continue. Sync performs the same commit followed by bounded
wait_for_response. Timeout returns pending state while delivery, response
collection and notification continue.

message_submission contains operation, Message identity, delivery state,
response handle and notification state. Follow-ups include read_message,
wait_for_response and set_notification with complete arguments.

## Waiting and notification

watch_changes creates a durable event subscription. send_message automatically
creates response tracking when a response is expected.

wait_for_response accepts one or more response handles, mode any or all, a
receipt or terminal condition, and timeout_seconds. It holds no database
transaction while waiting.

Completion notification uses response identity and completion revision for
deduplication. Projection retry, duplicate native result, Node restart and
Durable Operation retry converge on one notification. The current initiating
Session receives a wake when its Harness supports it. Project or AgentSlot Inbox
state remains available after Session replacement.

set_notification changes notification delivery while response state and Inbox
history remain independent.

## Reading

read_resource is a pure typed-handle read for Project, Route, WorkItem, Evidence,
Artifact and AcceptedState. It supports summary, detail, content, history and
evidence views at an exact revision.

read_message reads Message or response content. consume defaults to true and
records owner consumption atomically.

check_inbox lists durable Messages, response completions, Review requests and
recovery notifications for the project management or AgentSlot context.

## Review and acceptance

request_review binds the Review to candidate, exact source baseline, criteria,
evidence requirements and reviewer constraints.

The optional evidence_handles field selects the evidence set explicitly. The
request seals the complete candidate inventory and discloses unselected records.
Passing submit_review requires evidence_dispositions for every excluded record;
failed or uncertain evidence needs selected verified replacements and an explicit
Reviewer rationale. New candidate evidence invalidates that sealed inventory.
Original records and their source classes remain unchanged.

submit_review records decision, findings, evidence handles, exact source
readback and unresolved items.

accept_work commits an accepted-state revision after authorization, required
Review, evidence, source readback and protected-effect readback. Product-owner
and Finalizer boundaries remain explicit Policy decisions.

## Source access

Source read tools operate through authorized SourceBindings. Output is bounded
and revision-specific. Larger file or diff content returns immutable Artifact
references.

Source write tools are exposed only by an admitted Source-write Profile. They
bind WorkItem lineage and exact tree or commit preconditions and return protected
readback.

External GitHub MCP remains a valid parallel Source Provider. The ACS Skill uses
load_project SourceBinding metadata to coordinate GitHub reads without
duplicating GitHub credentials or repository authority.

## Advanced command surface

submit_command accepts one complete authenticated Domain SurfaceCommand for
operator, migration and conformance flows. The run alias returns the same
Domain disposition. Ordinary collaboration uses the typed tools.

## Knowledge Skill layer

The setup Skill owns guarded installation and migration procedures. Runtime
Skills are domain knowledge modules rather than fixed task recipes. They explain
entities, authority, invariants, decision axes, evidence boundaries and tool
implications so an external Agent can compose actions for current and future
goals.

The Harness initially receives Skill name and description. A semantic match,
resource state, knowledge_hint or explicit invocation loads the applicable
SKILL.md. The Agent follows one model, decisions or tools reference when that
detail is material and expands into an adjacent Skill only when the task crosses
its boundary.

MCP tools remain the authenticated data and action layer. Domain Command remains
the deterministic internal transition protocol. ProjectContextPack, AGENTS,
SourceBindings and project knowledge supply current project facts.

The adopted catalog is [skills/README.md](skills/README.md), the machine catalog
is [p2-skill-contract.json](p2-skill-contract.json), and runtime presentation is
[skills/RUNTIME-PRESENTATION.md](skills/RUNTIME-PRESENTATION.md).

## P2 acceptance

P2-MCP-WORKFLOW proves typed collaboration, delivery, response, notification,
reading, cancellation and Skill knowledge routing from real Codex and OpenCode clients.
P2-MANAGEMENT-WORKFLOW then proves local and web context hydration, cross-project
management, Source reads, Review workflows and project Inbox recovery. Each
scenario binds exact source, Profile, versions, credentials, direction, policy,
expiry and direct result bytes.
