---
name: acs-finalize-work
description: Validate and finalize ACS work after integrated-source, review, evidence, effect, publication, and product-owner requirements are satisfied. Use for acceptance, merge or release readiness, and final project-state updates.
---

# ACS Finalize Work

Canonical tools: load_project, read_resource, read_source, list_reviews, list_evidence, accept_work.

1. Load the project with context_view finalizer.
2. Read the current WorkItem, candidate and expected revision.
3. Read integrated source state and verify commit, tree, tests and remote
   readback for the candidate being accepted.
4. List required Reviews and Evidence and read their exact handles.
5. Verify protected-effect state and publication readback.
6. Preserve every unresolved item and evaluate the applicable Policy.
7. Call accept_work only when the authenticated subject owns the required
   acceptance permission and the decision input is present.
8. Return the AcceptedState handle, revision, source and evidence bindings,
   publication state and any remaining owner action.

Acceptance, source publication and product-owner decision remain distinct
records even when one user request authorizes more than one step.
