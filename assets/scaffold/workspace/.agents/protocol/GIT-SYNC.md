# Repository Synchronization

The Root may be non-Git. Repository state is therefore an explicit evidence
object, not an unconditional startup assumption.

For a source-repository handoff, state branch, base/head commit, tree, working
tree, push result, and receiver action. For a management-only task, state that
the repository is `not-applicable` or `unknown` rather than inventing Git data.

Message relay and repository synchronization remain independent. A delivered
message never proves that a receiver fetched or pulled the source repository.

Lifecycle:

```text
inspect -> bind source evidence -> modify -> verify -> capture knowledge
-> commit -> push when authorized -> report receiver sync action
```
