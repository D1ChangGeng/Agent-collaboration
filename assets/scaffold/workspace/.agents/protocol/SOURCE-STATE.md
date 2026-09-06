# Source State Evidence

The management workspace may describe a product without being its source
repository. Every implementation claim must identify the Source State Evidence
it relies on.

```yaml
kind: git | non-git | unknown
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
execution_endpoint:
  id: unknown
  host: unknown
  harness: unknown
  session: unknown
  status: unknown
evidence:
  class: direct | reported | external | baseline | unknown
  source: unknown
  observed_at: unknown
  freshness: unknown
  refresh_trigger: source, endpoint, branch, or deployment identity change
```

Missing values remain `unknown`, `unverified`, or `not-measured`; they are never
filled from a directory name, historical report, or Harness brand. A valid
initial baseline may be reused until its refresh trigger fires. If no valid
baseline exists, collect only the targeted fields needed for the next action.

GitHub, GitLab, or another host is a provider/adapter, not a protocol
requirement. Git remains the preferred durable source-state bridge when a source
repository exists.
