# Repository Synchronization

In the primary layout, the Management Root is nested in the Source Checkout
Root. Product code, management documents, knowledge, and Route directories are
tracked in the same Git repository. Repository state is evidence from the
specific checkout involved in the task.

Local and remote hosts use distinct clones with the same repository-relative
Management Root and Route layout. Absolute paths may differ. Commit and push
authorized changes explicitly; the receiver must fetch or pull explicitly and
verify the required baseline. A sender's clean tree or successful push does not
establish the receiver's state.

For a handoff involving tracked source or management changes, state branch,
base/head commit, tree, working tree, push result, and receiver action. Preserve
uncommitted work and resolve overlap before applying an incoming baseline.

The Source Checkout Root's `.gitignore` owns scoped rules for transient files
and secrets. Keep the nested Management Root's durable documents and Route
knowledge trackable; the nested Management Root has no child `.gitignore`.

Standalone management workspaces remain a compatibility deployment. Establish
whether a task involves a Git repository before stating its branch or commit;
use `not-applicable` only when verified, and `unknown` for missing evidence.

Message relay and repository synchronization remain independent. A delivered
message never proves that a receiver fetched or pulled the source repository.

Lifecycle:

```text
inspect -> bind source evidence -> modify -> verify -> capture knowledge
-> commit -> push when authorized -> report receiver sync action
```
