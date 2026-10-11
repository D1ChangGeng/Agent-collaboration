---
name: acs-source-evidence
description: SourceBinding, repository, filesystem, Git, branch, commit, tree, worktree, push, synchronization, Artifact, Evidence, digest, and readback knowledge for ACS. Use for source-aware management, review, handoff, acceptance, or web file access.
---

# acs-source-evidence

## Knowledge boundary

Source and evidence truth. Review decisions belong to acs-review-acceptance; execution placement belongs to acs-runtime-model.

## Core invariants

- Source content remains authoritative in its filesystem or repository provider and within the configured Source roots.
- Owner current workspace reads capture admitted tracked edits and untracked files under a workspace revision distinct from the Git baseline.
- Fixed revision and commit snapshots retain exact bytes, modes, digests and provenance for reproducible work.
- Message delivery and Git synchronization are separately observed facts.
- Artifact bytes, Evidence claims and ExecutionReceipt facts retain separate identities; historical facts preserve their recorded context after a former Grant's natural expiry.
- Imported and endpoint-reported observations retain provenance; current source and readiness claims require current readback.

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

Apply this knowledge to the user's goal and current evidence. Read the
installed access mode and active tool schema, then compose actions from trusted
identity, object state, revisions and required readback. References explain
durable semantics; ProjectContextPack and current sources provide project facts.
The owner product contract is `docs/runtime/OWNER-RUNTIME.md` in the verified
ACS release or source checkout.

## Related knowledge

Expand into an adjacent domain when the task crosses this Skill boundary:

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
