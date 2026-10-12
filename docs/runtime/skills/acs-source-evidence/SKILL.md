---
name: acs-source-evidence
description: SourceBinding, machine files, repository, Git, branch, commit, tree, worktree, push, synchronization, Artifact, Evidence, digest, and readback knowledge for ACS. Use for source-aware management, review, handoff, acceptance, or web file access.
---

# acs-source-evidence

## Knowledge boundary

Source and evidence truth. Review decisions belong to acs-review-acceptance;
execution placement and machine connections belong to acs-runtime-model.

## Core invariants

- SourceBinding supplies advisory repository, location and version hints; the Agent chooses an actually available reader.
- Owner machine tools operate on current files under the selected OS account. Machine, account, directory and cursor identify the actual read.
- Explicit Source tools resolve the Project product default or a selected Source/root/revision. Captured pagination retains the returned view_revision.
- primary_source_root identifies the preferred repository location; current Source reads resolve its physical primary worktree, actual branch and edits.
- Source actual_source reports provider/root/commit/tree/view_revision/observed_at. current_readable_root and origin_hint describe their own locations.
- Product source_observation and distinct management_source_observation retain separate context; unavailable product defaults have null product observation and references.
- Review/Evidence bind the actual candidate/source identity. Shared access/version checks and each reader's authority remain effective.

## Retrieval map

Read the smallest reference that resolves the material question.

| Question | Reference |
|---|---|
| Machine files, SourceBinding and evidence entities | [model](references/model.md) |
| Reader choice, baseline, sync and readback decisions | [decisions](references/decisions.md) |
| Current file and Source/evidence tools | [tools](references/tools.md) |

## Tool vocabulary

Relevant tools: filesystem_context, select_filesystem, read_file,
list_directory, glob, grep, write_file, edit_file, apply_patch, list_sources,
read_source_file, list_source_files, search_source_files, read_source, read_diff,
list_evidence, read_resource.

Tool descriptions and the installed machine contract define exact invocation
schemas. This Skill explains authority, reader choice and evidence implications.

## Application

Apply this knowledge to the user's goal and current evidence. Read the installed
access mode and active tool schema, then choose the reader and record its actual
target and version where required. References explain durable semantics;
ProjectContextPack and current sources provide project facts. Product contracts
are `docs/runtime/MACHINE-FILESYSTEM.md` and
`docs/runtime/OWNER-RUNTIME.md` in the verified ACS release or source checkout.

## Related knowledge

- [acs-project-context](../acs-project-context/SKILL.md)
- [acs-review-acceptance](../acs-review-acceptance/SKILL.md)
- [acs-runtime-model](../acs-runtime-model/SKILL.md)
