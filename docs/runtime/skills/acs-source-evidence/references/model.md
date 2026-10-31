# acs-source-evidence: model

Source provenance and actual file access. ACS messages carry references, not repository synchronization.

- Prefer accessible paths, Git and existing authorized readers. Record the actual machine, account, path and version read.
- Core service local is not every Agent's local machine. A Source snapshot is not automatically the current working tree.
- Mentioning a path in a message does not trigger copying, writes or Git operations. Work results belong in external files/repositories.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-model.md); it is not the current communication contract.
