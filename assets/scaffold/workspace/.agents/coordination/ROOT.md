# Project Collaboration Root

This file is a concise route into the full Root contract. The authoritative
Root↔Route migration and lifecycle rules are in `ROOT-BASELINE.md`; stable Route
identity is in `routes.yaml`; changing route state stays Route-owned.

Root responsibilities:

- maintain project identity and stable Route registry;
- preserve Root/Route ownership boundaries;
- coordinate only material sibling-route dependencies;
- point Routes to Source State Evidence and Execution Endpoints without
  inventing facts;
- provide a reviewable, idempotent migration path for legacy Routes.

Root is not a replacement for A/B Route knowledge and is not a source-code
execution node.
