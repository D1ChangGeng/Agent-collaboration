# Source State Evidence

The primary layout nests the Management Root in the project's Source Checkout
Root, with management documents, knowledge, Routes, and product code tracked in
the same Git repository. Management ownership, Source Repository state, and
Execution Endpoint identity remain logically separate. Every implementation
claim must identify the Source State Evidence it relies on.

Local and remote clones preserve the same repository-relative layout while
their absolute paths may differ. Inspect the relevant clone before binding
branch, commit, tree, worktree, push, or receiver-sync evidence. A shared layout
does not establish synchronized contents. Standalone management workspaces
remain a compatibility deployment and bind source evidence explicitly.

Do not create an empty Route state file merely to reserve the shape. When
verified source facts need to survive across Sessions, a Route may create the
optional `.agents/state/source-state.yaml` record from this minimal form:

```yaml
kind: git | non-git
repository:
  locator: unknown
  provider: unknown
  remote: unknown
  branch: unknown
  commit: unknown
  tree: unknown
  working_tree: unknown
  push: unknown
  receiver_sync: unknown
evidence:
  class: direct | reported | external | baseline
  source: unknown
  observed_at: unknown
```

Missing claims remain `unknown`, `unverified`, or `not-measured`; absence of the
optional file also means no durable Source State has been established. Never
fill values from a directory name, historical report, or Harness brand. Re-read
Git or the authoritative source before a consequential action when the recorded
identity may no longer be current.

Harness, Session, permission, process-liveness, and transient Endpoint
observations belong to the current execution context. Persist only a specific
Endpoint relationship that has independent long-term value, and place that fact
in the narrowest existing Route authority rather than extending this source
record into a live runtime-status surface.

GitHub, GitLab, or another host is a provider/adapter, not a protocol
requirement. Git remains the preferred durable source-state bridge when a source
repository exists.
