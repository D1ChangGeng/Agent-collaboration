# Collaboration model

## Logical entities

AgentSlot is the durable recipient and responsibility identity inside a Scope.
Principal identifies the collaborator. Role describes duties. Harness
requirements select the execution product. A replaceable Session can bind to
the Slot.

Owner team configuration records these business bindings. Shared deployments
also bind per-subject Grants, Policy, Profiles and budgets. Root and Route
describe responsibility extent. Engineer, Reviewer, Specialist and Finalizer
describe duties; candidate-specific independence checks govern Review.

WorkItem records goal, accepted state, constraints, dependencies, source
baseline and evidence requirements. Business budget or deadline is optional
where the selected mode permits it. Attempt records one execution try. Message
records one logical communication. Handoff records responsibility transfer.

## Independent state dimensions

WorkItem acceptance, execution, waiting, Review, effect, publication and source
synchronization advance independently. Attempt completion establishes its
execution result. Acceptance records a separate decision after the required
candidate checks. Message delivery and source synchronization have their own
receipts.

## Lineage and lifetime

Mutations retain authenticated subject, tenant, project_id, Scope, stable
request identity and expected revisions. Owner commands and Messages remain
valid by default while their service and target are active; an explicit
business deadline can bound a request. Shared mode additionally applies its
configured expiry and admission rules. System retries preserve the initiating
command and Message identities.

Team revisions preserve prior configuration and ownership. Session replacement
keeps durable work, Inbox, response and subscription identities.
