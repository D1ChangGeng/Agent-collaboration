# Collaboration model

## Logical entities

AgentSlot is the durable recipient and responsibility identity. Role describes
expected behavior. Grant authorizes operations. Policy constrains decisions.
Budget limits admitted resource use. A Session can bind to a Slot and later be
replaced.

WorkItem records goal, accepted state, constraints, dependencies, source
baseline, evidence contract, budget and deadline. Attempt records one execution.
Message records one logical communication. Handoff records responsibility
transfer.

## Independent state dimensions

WorkItem acceptance, execution, waiting, Review, effect, publication and source
synchronization advance independently. A completed Attempt does not imply
accepted work. A delivered Message does not imply source synchronization.

## Lineage

Every team, WorkItem, handoff and Message mutation carries authenticated
subject, project_id, Scope, stable request identity, expected revision and
deadline. System retries preserve the initiating command lineage.
