---
name: acs-source-evidence
description: SourceBinding, repository, filesystem, Git, branch, commit, tree, worktree, push, synchronization, Artifact, Evidence, digest, and readback knowledge for ACS. Use for source-aware management, review, handoff, acceptance, or web file access.
---

# acs-source-evidence

## Knowledge boundary

Source and evidence truth. Review decisions belong to acs-review-acceptance; execution placement belongs to acs-runtime-model.

## Core invariants

- SourceBinding provides advisory repository, location and version hints; the Agent chooses an actually available reader.
- Owner defaults select the Project product repository; primary_source_root locates the preferred repository and current reads resolve its physical primary worktree, actual branch and edits.
- Explicit source_root selects a configured readable current location; explicit revision selects captured bytes, and pagination retains the returned view_revision.
- Owner actual_source reports provider/root/commit/tree/view_revision/observed_at; current_readable_root and origin_hint describe their own locations.
- Owner product source_observation and distinct management_source_observation retain separate context; unavailable product defaults have null product observation and references.
- Review/Evidence bind actual candidate/source identity; shared access/version checks and provider boundaries remain effective, and source location is separate from execution placement.

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
