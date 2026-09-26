# Capability Matrix

This matrix records the current support truth of `agent-collaboration-setup`.
It is an evidence ledger, not a roadmap. A capability is not `supported` merely
because it appears in the Canonical Spec or in a template. The minimum support
claim requires:

```text
instruction
+ decision logic
+ real mechanism
+ invariant validation
+ representative end-to-end evidence
```

The matrix is intentionally conservative. `narrow` means a bounded CLI/file
journey, not a general natural-language or distributed-runtime guarantee.

## Status legend

| Status | Meaning |
|---|---|
| `supported (narrow)` | All five support layers exist for a bounded local scenario. |
| `supported (protocol)` | A portable protocol/policy is defined; provider runtime behavior remains external. |
| `partial` | At least one layer or important safety boundary is incomplete. |
| `documented / unverified` | Instructions exist, but current-environment evidence is missing. |
| `architecture-allowed` | The design permits the capability; the current Skill does not implement it. |
| `unsupported` | No honest current mechanism exists. |
| `unknown` | The fact depends on the current Harness/host and has not been measured. |

## Current matrix

| Capability | Instruction | Decision | Mechanism | Invariant validation | Representative evidence | Current status | Truthful user wording |
|---|---:|---:|---:|---:|---:|---|---|
| Skill discovery and explicit invocation | ✓ | ✓ | ✓ | ✓ | local validator | `supported (narrow)` | “The Skill can be explicitly loaded for setup maintenance.” |
| Repository bootstrap on a genuinely new target | ✓ | ✓ | ✓ | ✓ | setup tests / temporary repository | `supported (narrow)` | “Repository bootstrap is bounded to a missing or empty target; review the preview.” |
| Repository adopt with project preservation | ✓ | ✓ | ✓ | ✓ | setup tests / temporary repository | `supported (narrow)` | “Adopt preserves project content and refuses ambiguous ownership.” |
| Repository upgrade | ✓ | ✓ | ✓ | ✓ | schema/upgrade tests | `supported (narrow)` | “Explicit managed-template upgrade is supported for the tested repository shape.” |
| Repository repair | ✓ | ✓ | ✓ | ✓ | setup tests / temporary repository | `supported (narrow)` | “Repair restores only missing, provably managed setup components.” |
| Repository validate | ✓ | ✓ | ✓ | ✓ | validator and unit tests | `supported (narrow)` | “Validation reports managed-file, marker, ownership, and routing invariants.” |
| Workspace bootstrap/adopt at an exact path | ✓ | ✓ | ✓ | ✓ | temporary Workspace and alias-refusal scenarios | `supported (narrow)` | “Workspace setup and read/Route entry points reject symlink, junction, and reparse aliases for the tested states.” |
| Workspace upgrade from schema 0.2 | ✓ | ✓ | ✓ | ✓ | compatibility tests | `supported (narrow)` | “Schema 0.2 input remains readable; explicit upgrade canonicalizes supported metadata.” |
| Workspace repair | ✓ | ✓ | ✓ | ✓ | temporary Root partial-state scenarios | `supported (narrow)` | “Workspace repair restores missing Root-owned setup components; Route-owned gaps use `route adopt`.” |
| Workspace validate | ✓ | ✓ | ✓ | ✓ | temporary Workspace and alias-refusal validation | `supported (narrow)` | “Workspace invariants can be checked at the exact supplied non-reparse path; this does not prove runtime continuity.” |
| Workspace uninstall | ✓ | ✓ | ✓ | ✓ | guarded refusal tests | `supported (narrow)` | “Workspace uninstall is guarded and currently refuses mutation without an ownership plan.” |
| Route create | ✓ | ✓ | ✓ | ✓ | absent-path, idempotency, existing-path, and ID/path tests | `supported (narrow)` | “A new Route is created only at an absent path; existing unregistered work must use `route adopt`.” |
| Route adopt | ✓ | ✓ | ✓ | ✓ | Route preservation, custom-ID, and partial dry-run/apply tests | `supported (narrow)` | “An existing Route can be previewed and adopted while preserving its durable identity and existing Route-owned content.” |
| Route list and registry read | ✓ | ✓ | ✓ | ✓ | registry tests | `supported (narrow)` | “The Root registry can list stable Route identity and lifecycle facts.” |
| Route validate | ✓ | ✓ | ✓ | ✓ | route scaffold, metadata, and exact-path tests | `supported (narrow)` | “Route validation checks the complete required scaffold and identity at the exact supplied Workspace path.” |
| Route set-state / rename metadata | ✓ | ✓ | ✓ | ✓ | registry-only tests | `supported (narrow)` | “State and display-name metadata can be changed in the Root registry.” |
| Route metadata upgrade | ✓ | ✓ | ✓ | ✓ | legacy metadata tests | `supported (narrow)` | “Route upgrade canonicalizes metadata; it is not collaboration migration.” |
| Schema 0.2 read compatibility | ✓ | ✓ | ✓ | ✓ | legacy fixture tests | `supported (narrow)` | “Legacy schema 0.2 records are readable and handled conservatively.” |
| Optional durable Route Source State | ✓ | ✓ | ✓ | partial | template/creation tests | `partial` | “Verified source facts may be recorded when they have durable cross-Session value.” |
| Empty Source State suppression | ✓ | ✓ | ✓ | ✓ | Route creation tests | `supported (narrow)` | “New Routes do not receive a fabricated unknown runtime record.” |
| Manual user relay | ✓ | ✓ | protocol only | protocol checks | document/packet fixtures | `supported (protocol)` | “Manual forwarding is the portable relay mode.” |
| Direct same-host relay | partial | partial | — | — | no current E2E | `unverified` | “Do not assume direct relay; verify the exact Harness capability first.” |
| Direct cross-host relay | partial | partial | — | — | no current E2E | `unsupported` by this Skill | “The Skill does not provide cross-host direct relay.” |
| Session enumeration and targeting | partial | — | — | — | no current adapter | `unsupported` by this Skill | “Session addressing belongs to a Harness adapter, not this setup Skill.” |
| Session attach / replacement | ✓ conceptually | ✓ conceptually | — | — | no current E2E | `architecture-allowed` | “Route identity survives a new Session in principle; attach is not a current command.” |
| Execution Endpoint binding | ✓ conceptually | partial | — | — | no current adapter | `architecture-allowed` | “Endpoint facts remain external and unverified.” |
| Endpoint replacement / machine migration | ✓ conceptually | ✓ conceptually | — | — | no current E2E | `unsupported` by this Skill | “No current deterministic Endpoint replacement operation exists.” |
| Collaboration configuration migration | ✓ conceptually | ✓ conceptually | — | — | no current mechanism | `unsupported` by this Skill | “Metadata upgrade does not migrate collaboration behavior.” |
| Local source access | ✓ policy | external | external | — | environment-dependent | `documented / unverified` | “Local access must be checked in the actual environment.” |
| Git source synchronization | ✓ policy | external | external | external | no Skill-owned sync E2E | `documented / unverified` | “Git remains an independent source-state bridge; the Skill does not perform day-to-day sync.” |
| SSH source access | ✓ design | partial | — | — | no SSH adapter/E2E | `architecture-allowed` | “SSH is an allowed topology in the design, not a current Skill capability.” |
| Git + SSH combined workflow | ✓ design | partial | — | — | no E2E | `documented / unverified` | “The combination requires separately verified source and transport mechanisms.” |
| Natural-language intent routing | partial | — | — | — | no automated journey E2E | `unsupported` as an automatic Skill mechanism | “An Agent can use the operating guide, but the scripts do not parse intent.” |
| Minimum interview support | ✓ guide | Agent-owned | — | — | no harness E2E | `documented / unverified` | “The guide defines when to ask; no interview state is persisted.” |
| Root/Route attachability proof | ✓ target | partial | — | — | no attach E2E | `unsupported` by current Skill | “Validation proves files and identity, not future Session attach.” |
| Cross-Harness discovery routing | ✓ compatibility docs | external | thin files | partial | static compatibility only | `documented / unverified` | “Instruction routing is documented; runtime capabilities must be measured per Harness.” |
| Harness shell/filesystem capability | external | external | external | external | current session only | `unknown` | “Report only what this current Harness and host actually expose.” |

## Evidence handling rules

1. Cite the actual test, command output, temporary directory, or read-back file
   that proves a row. A prose design statement is not mechanism evidence.
2. Keep provider-specific runtime observations scoped to the current Session,
   Harness version, host, permissions, and installed tools.
3. Treat missing evidence as `unknown`, `unverified`, or `not-measured`, never
   as success by default.
4. Re-run the relevant scenario after any mechanism change. Do not upgrade a
   row because a new script branch exists until invariant and E2E checks pass.
5. If the mechanism is intentionally outside this setup Skill, say so; do not
   create a second source of truth or a hidden runtime dependency.

## Matrix maintenance

Update this file only when a real implementation or verification changes a
capability boundary. Keep proposed work in a roadmap/decision record instead
of changing a status row early. A release should include the matrix state that
was actually verified for that release.
