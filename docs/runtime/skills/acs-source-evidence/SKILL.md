---
name: acs-source-evidence
description: SourceBinding, machine files, repository, Git, branch, commit, tree, worktree, push, synchronization, Artifact, Evidence, digest, and readback knowledge for ACS. Use for source-aware management, review, handoff, acceptance, or web file access.
---

# acs-source-evidence

## Knowledge boundary

Source and evidence truth. Review decisions belong to acs-review-acceptance;
execution placement and machine connections belong to acs-runtime-model.

## Core invariants

- Owner machine tools operate on current files under the selected OS account. Machine, account, directory and cursor identify the actual read.
- Owner Project context loads current management documents from its registered machine and directory; configuration can set, replace or clear that location.
- The Agent chooses an available machine, native, Git or repository reader and reports the source version actually inspected.
- Owner WorkItem.source_baseline may be omitted or null. Eligible intent revisions can select, change or clear that work version.
- Historical SourceBinding records and captured views are an explicit archive, selected by source_id and revision. Captured pagination retains view_revision.
- Review and acceptance bind the exact candidate, reported commit/tree and recorded Evidence. Historical facts retain their original source, author and digests.
- Shared access/version checks and each reader's authority remain effective under their recorded contract.

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
