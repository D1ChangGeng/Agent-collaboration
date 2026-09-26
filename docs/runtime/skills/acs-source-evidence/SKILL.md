---
name: acs-source-evidence
description: SourceBinding, repository, filesystem, Git, branch, commit, tree, worktree, push, synchronization, Artifact, Evidence, digest, and readback knowledge for ACS. Use for source-aware management, review, handoff, acceptance, or web file access.
---

# acs-source-evidence

## Knowledge boundary

Source and evidence truth. Review decisions belong to acs-review-acceptance; execution placement belongs to acs-runtime-model.

## Core invariants

- Source content remains authoritative in its filesystem or repository provider.
- Source claims bind repository identity, revision, commit, tree and observed worktree state.
- Message delivery and Git synchronization are independent.
- Artifact bytes, Evidence claims and ExecutionReceipt facts are separate.
- Imported or endpoint-reported observations retain provenance and do not become verified by storage alone.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| SourceBinding and evidence entities | [model](references/model.md) |
| Provider choice, baseline, sync and readback decisions | [decisions](references/decisions.md) |
| Source and evidence tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: list_sources, list_files, search_files, read_file, read_source, read_diff, list_evidence, read_resource.

Tool descriptions and the machine contract define exact invocation schemas.
This Skill explains the model, authority and decision implications around those
tools.

## Application

Apply this knowledge to the user's actual goal and current evidence. Compose
tools from present state, permissions and required readback. Examples in the references illustrate the model. The Agent derives the
sequence from current state, authority, evidence and the user's goal.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
