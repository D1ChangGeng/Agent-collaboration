# Project Collaboration Root

This file is a concise route into the full Root contract. The authoritative
Root↔Route migration and lifecycle rules are in `ROOT-BASELINE.md`; stable Route
identity and lifecycle status are in `routes.yaml`; durable Route goals,
decisions, knowledge, and source evidence remain in the Route.

Root responsibilities:

- maintain project identity and stable Route registry;
- preserve Root/Route ownership boundaries;
- coordinate only material sibling-route dependencies;
- point Routes to Source State Evidence and Execution Endpoints without
  inventing facts;
- provide a reviewable, idempotent migration path for legacy Routes.

Root is not a replacement for Route knowledge and is not a source-code
execution node. Live Session progress remains in the current Harness context.
