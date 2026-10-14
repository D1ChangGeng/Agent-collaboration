---
name: acs-review-acceptance
description: Review, reviewer independence, candidate, findings, evidence sufficiency, integrated baseline, finalization, acceptance, publication, and product-owner boundary knowledge for ACS. Use when evaluating or accepting architecture, engineering, evidence, or release results.
---

# acs-review-acceptance

## Knowledge boundary

Evaluation and accepted state. Source truth belongs to acs-source-evidence; authorization belongs to acs-policy-governance.

## Core invariants

- Review binds an exact candidate, its recorded Evidence and the WorkItem's selected source baseline when present.
- Owner Review and acceptance use the commit/tree actively observed and reported by the Agent through Git, native tools or machine files.
- An optional work version can be selected, changed or cleared through eligible intent revisions; recorded candidate Evidence preserves its original contents and provenance.
- Reviewer independence is a verified candidate-specific identity and assignment property in the adopted acceptance profile.
- Architecture, engineering, evidence and finalization Reviews answer distinct questions.
- Owner access preserves candidate checks, hashes, deterministic storage, authorized decisions and historical Review provenance.
- Attempt completion, Review pass, publication and AcceptedStateRevision are separately recorded facts.
- Acceptance evaluates integrated evidence, protected effects, readback, unresolved items and applicable product-owner decisions; shared admission retains its Grant, Policy and Source checks.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Review and acceptance entities | [model](references/model.md) |
| Selecting review type and deciding readiness | [decisions](references/decisions.md) |
| Review, evidence and acceptance tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_reviews, request_review, submit_review, list_evidence, read_file, read_diff, read_source, accept_work, revise_work.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The owner product contract is `docs/runtime/OWNER-RUNTIME.md` in the verified
ACS release or source checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-source-evidence](../acs-source-evidence/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
