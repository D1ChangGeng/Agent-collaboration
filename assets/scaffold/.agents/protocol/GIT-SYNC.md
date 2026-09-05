# Repository Synchronization

Git state and session messaging are separate.

## Start of repository-dependent work

1. inspect working tree;
2. identify branch and HEAD;
3. preserve uncommitted work;
4. fetch when safe and available;
5. compare local and remote;
6. synchronize only when safe and permitted;
7. if diverged/unsafe, report instead of using destructive reset/clean operations.

## End of durable repository work

```text
modify
-> verify
-> capture durable knowledge/decisions if warranted
-> commit
-> push when permitted
-> handoff exact baseline
```

## Explicit states

Use:

```text
NO_REPO_CHANGE
LOCAL_ONLY
COMMITTED_NOT_PUSHED
PUSHED_RECEIVER_PULL_REQUIRED
SYNCHRONIZED
DIVERGED_MANUAL_RESOLUTION_REQUIRED
```

## Handoff repository block

```yaml
repository:
  branch: main
  base_commit: <sha>
  head_commit: <sha>
  working_tree: clean
  push: complete
  receiver_sync: pull-required
```

The receiver must verify it has the handoff commit before implementation or review.

Architecture, product, roadmap, decision, and knowledge documents are repository state too.
