# Scenario Regression Matrix

This matrix turns the user-journey audit into repeatable checks. It records the
semantic decision an Agent should make, the deterministic mechanism currently
available, and the truthful support boundary. `PASS` means the bounded current
scenario has evidence; `PARTIAL` means only some layers are closed; `GAP` means
the design or guide exists without a complete mechanism; `BLOCK` means the
current Skill cannot honestly perform the journey.

The matrix is deliberately about behavior and evidence, not wording snapshots.
Natural-language examples are prompts for Agent reasoning; they do not imply
that the Python CLI parses those phrases.

## Root and Route lifecycle

| ID | Scenario / initial state | Agent decision | Current mechanism | Required read-back | Status |
|---:|---|---|---|---|---|
| 1 | Target directory does not exist | Resolve exact path; create the requested object only after intent is clear | Workspace/repository bootstrap paths | Target, manifest, managed files, validation | `PASS` for explicit Workspace setup and exact-path guards |
| 2 | Empty directory | Confirm it is the intended Root/repository | Bootstrap according to mode | Required scaffold and identity | `PASS` |
| 3 | Non-empty ordinary project directory | Preserve assets; adopt rather than bootstrap | Workspace/repository adopt | Existing files, ownership, conflicts, validator | `PASS` for tested local shapes |
| 4 | Legacy Root/schema 0.2 | Use explicit upgrade boundary | Workspace/Route upgrade | Schema, identity, preserved extension fields | `PASS` in tested legacy fixtures |
| 5 | Current valid Root and user wants to continue | Preserve Root; interpret next goal, do not re-bootstrap | Validate/read existing files; no attach command | Identity and current context | `BLOCK` for attach |
| 6 | Partial or interrupted setup | Inspect ownership and distinguish Root-owned from Route-owned gaps | Repository repair; Root `workspace repair`; Route `route adopt` dry-run/apply | No unrelated overwrite; final validation | `PASS` for tested Root and Route missing-scaffold shapes |
| 7 | New long-lived Route | Create one new Route identity | `route create` | Route metadata, registry, scaffold | `PASS` |
| 8 | Existing long-lived work not registered | Adopt in that Route's own migration phase and preserve its identity | `route adopt`; valid existing metadata supplies a custom ID when omitted | Existing AGENTS, knowledge, refs, state preserved | `PASS` for tested explicit-ID, metadata-ID, and partial-scaffold shapes |
| 9 | Fresh Session enters registered Route | Keep Route identity and attach Session semantically | No current attach API | Session addressability and inherited context | `BLOCK` |
| 10 | Route system/schema update | Canonicalize metadata only | `route upgrade` | Metadata and registry, Route content preserved | `PASS` for tested schema migration |
| 11 | Collaboration behavior changes | Treat as explicit collaboration migration | No current migration command | Configuration diff and preserved semantics | `BLOCK` |
| 12 | Local source access requested | Inspect actual local source relationship | External/local environment | Path, repository state, permissions | `GAP` / environment-dependent |
| 13 | Remote Engineer with user relay | Keep Route; use manual relay if needed | Relay protocol documents envelope | User-forwarded packet and source facts separately | `PARTIAL` |
| 14 | Separate clones with Git synchronization | Keep message and Git dimensions independent | Git policy/documentation | Branch, HEAD, dirty state, push/pull evidence | `DOCUMENTED / UNVERIFIED` |
| 15 | Direct relay appears available | Verify exact send/address/delivery capability | No Skill-owned direct relay adapter | Delivery/read-back evidence | `UNVERIFIED` |
| 16 | Direct relay unavailable | Fall back to manual user relay | Relay policy | Complete copy-ready envelope | `PASS` at policy level |
| 17 | SSH source access requested | Treat SSH as source access, not Git or relay | No SSH adapter in Skill | Remote read-back, authorization, source identity | `BLOCK` / external procedure required |
| 18 | Evidence-only source state | Persist only verified durable facts | Optional Route Source State | Provenance, scope, no runtime fields | `PARTIAL` |
| 19 | Git and SSH both used | Model each dimension separately | No combined Skill workflow | Independent Git and SSH evidence | `UNVERIFIED` |
| 20 | Source relationship pending | Allow Root/Route structure without fabricated baseline | No Source State file required | Explicit pending/unbound state | `PASS` |

## Runtime continuity and scale

| ID | Scenario / initial state | Agent decision | Current mechanism | Required read-back | Status |
|---:|---|---|---|---|---|
| 21 | Architect Session replaced | Preserve Root/Route identity | Harness context plus files; no attach API | Existing identity and current context | `GAP` |
| 22 | Engineer Session replaced | Preserve Route; re-resolve runtime capability | No Session broker | New Session addressability and handoff | `BLOCK` |
| 23 | Execution Endpoint replaced | Preserve Route; refresh Endpoint/source facts | No Endpoint binding/replacement | Endpoint, source, transport, baseline evidence | `BLOCK` |
| 24 | Engineer machine changes | Treat as Endpoint/machine migration | No migration operation | New host and source verification | `BLOCK` |
| 25 | Source checkout/baseline changes | Re-read authoritative source state | No baseline refresh command | Branch/commit/tree/worktree read-back | `BLOCK` as Skill lifecycle |
| 26 | Third, fourth, or arbitrary Route | Add another independent Route identity | Generic Route create/registry; use adopt for an existing path | Unique ID/path and registry | `PASS` for absent-path creation, existing-path refusal, and ID/path collision tests |
| 27 | Generic registry with many Routes | Keep stable four-field Route entries | Root registry | Duplicate/collision and list output | `PASS` in generic tests |
| 28 | Selective sibling communication | Send only required packet to named Route | Protocol guidance; no targeting API | Addressability, delivery, response | `GAP` |
| 29 | Root avoids per-turn shared-write hotspot | Keep dynamic state Route-owned/current-context | Minimal registry model | No per-turn Root churn | `PASS` design/invariant; no stress E2E |
| 30 | User uses non-system language for adoption | Infer existing assets and adopt | Agent guide; scripts need explicit mode | Correct command and preserved files | `GAP` automatic routing |
| 31 | User says “继续原来的路线” | Attach/continue existing Route; never create | No attach mechanism | Identity unchanged | `BLOCK` |
| 32 | User provides topology facts | Do not ask the same facts again | Agent guide | Questions limited to behavior-changing unknowns | `GAP` no journey E2E |
| 33 | Optional metadata exists | Keep it out of minimum interview | Minimal schema and guide | No unnecessary durable fields/questions | `PARTIAL` |
| 34 | Agent reads only entrypoint guidance | Select lifecycle safely and honor command boundaries | SKILL routes to Operating Guide; no intent parser | Correct decision for representative prompts | `GAP` pending independent natural-language forward test; deterministic lifecycle boundaries are documented and tested |
| 35 | Scripts report facts while Agent decides semantics | Keep scripts deterministic and bounded | CLI commands and validators | Facts/actions/errors are distinguishable | `PASS` for tested CLI surfaces |

## Safety, validation, and finalization

| ID | Scenario / initial state | Agent decision | Current mechanism | Required read-back | Status |
|---:|---|---|---|---|---|
| 36 | Adopt target contains user assets | Preserve all project-owned content | Managed blocks/ownership checks | Asset hashes/list and diff review | `PASS` for tested Workspace and repository shapes |
| 37 | Upgrade target contains durable knowledge | Preserve knowledge and Route state | Explicit upgrade boundaries | Knowledge paths unchanged and validation | `PASS` in tested Workspace/Route cases |
| 38 | Dry-run requested | Preview without writes | `--dry-run` | Before/after snapshot equal | `PASS` |
| 39 | Dirty/diverged Git state | Preserve user work; stop unsafe sync | Git policy/documentation | Branch/HEAD/status and no destructive mutation | `UNVERIFIED` in this Skill |
| 40 | External action is reported | Claim only observable action/result | Handoff/report conventions | Read-back evidence and exact status | `PARTIAL` |
| 41 | Final state is read back | Use final filesystem/repository state as authority | Validators and explicit reports | Final snapshot after mutation | `PASS` for release/setup checks; journey-wide `PARTIAL` |
| 42 | Non-standard language maps to adopt | Infer intent only when safe | Operating Guide | Correct mode and no overwrite | `GAP` pending forward test |
| 43 | “Continue” must not create Route | Preserve existing identity | Guide only; no attach command | Registry unchanged | `BLOCK` for full journey |
| 44 | Reopened Engineer window must not create Route | Session replacement, not Route creation | Guide only | Route ID/path unchanged | `BLOCK` |
| 45 | Topology already supplied | Avoid redundant questions | Guide rules | Question transcript or Agent trace | `GAP` |
| 46 | Agent explains why a question is needed | Ask only behavior-changing unknowns | Guide examples | User can see the decision impact | `GAP` |
| 47 | Entrypoint alone selects lifecycle | Read guide before command choice | SKILL routing | Representative natural-language decisions | `GAP` |
| 48 | Agent has no source-code access | Use references and CLI facts without guessing | Packaged docs and scripts | Correct boundary labels | `PARTIAL` |
| 49 | Scripts do not hide semantic decisions | Agent owns intent; script owns mechanics | Explicit command families | Action output and error category | `PASS` for tested CLI surfaces |
| 50 | Same operation works across phrasing | Normalize to deterministic command after decision | CLI itself is phrase-independent | Same target invariant for equivalent intent | `PASS` at CLI level; Agent routing `GAP` |

## Required evidence for a future “complete journey” claim

To change a `BLOCK`, `GAP`, or `UNVERIFIED` row to a supported claim, capture
all of the following for the relevant scenario:

1. the exact user request or a sanitized equivalent;
2. the observed initial filesystem/Harness state;
3. the Agent's lifecycle decision and any minimum question asked;
4. the deterministic command or adapter invocation;
5. invariant validation and final read-back;
6. preservation/diff evidence for project-owned data;
7. capability-specific evidence for Session, Endpoint, source, SSH, or relay
   claims;
8. exact repository branch/HEAD/push state when repository changes are part of
   the scenario.

Do not use a green unit-test aggregate, a design document, a historical report,
or a successful command exit code as a substitute for the complete journey.
