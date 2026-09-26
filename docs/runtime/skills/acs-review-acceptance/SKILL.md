---
name: acs-review-acceptance
description: Review, reviewer independence, candidate, findings, evidence sufficiency, integrated baseline, finalization, acceptance, publication, and product-owner boundary knowledge for ACS. Use when evaluating or accepting architecture, engineering, evidence, or release results.
---

# acs-review-acceptance

## Knowledge boundary

Evaluation and accepted state. Source truth belongs to acs-source-evidence; authorization belongs to acs-policy-governance.

## Core invariants

- Review is bound to an exact candidate and source baseline.
- Reviewer independence is a verified identity and assignment property.
- Architecture, engineering, evidence and finalization reviews have distinct questions.
- Attempt success, Review pass, publication and accepted state are separate facts.
- Acceptance preserves unresolved items and applicable Policy and product-owner boundaries.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Review and acceptance entities | [model](references/model.md) |
| Selecting review type and deciding readiness | [decisions](references/decisions.md) |
| Review, evidence and acceptance tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_reviews, request_review, submit_review, list_evidence, read_diff, read_source, accept_work.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-source-evidence](../acs-source-evidence/SKILL.md)
- [acs-policy-governance](../acs-policy-governance/SKILL.md)
- [acs-collaboration-model](../acs-collaboration-model/SKILL.md)
