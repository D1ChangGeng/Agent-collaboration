# Inspect project source locations

Agents inspect source through the machine, native, Git or repository tools
available to them. The Runtime service host, client host, Management Root and
product source location are separate facts. A project can have several clones
with different branches and revisions. The Agent actively chooses the work
version and records the source that supports each candidate.

Owner project registration starts from the initialized Management Root and its
current machine and directory. It supports nested Git and standalone management
directories. Source discovery is an optional inspection step when the work needs
repository identity or a chosen source version.

## Agent discovery sequence

1. Inspect the active project directory and configured Management Root. Read its
   manifest and current instructions through the available file tools. When
   source facts matter to the task, inspect the actual product files and Git
   metadata where available. Existing `list_sources` metadata provides recorded
   repository and historical view references for explicit archive queries.
2. Derive candidate locations from current project context and the user's
   authorized machine connections. Inspect exact paths and relevant parent
   directories. An SSH alias identifies an address candidate; the authorized
   project inspection scope determines which paths may be probed.
3. Use machine or native tools for current files. For a Git checkout, the
   read-only discovery helper can inspect each relevant candidate using the
   target machine's path spelling. Compare Project/Root identity, repository,
   machine/account, commit/tree, branch and working tree.
4. Choose the working copy from verified observations. If several copies differ
   materially and the intended source remains unresolved, present their actual
   host/path/revision differences and request the smallest missing decision.
   Report unavailable access with its exact path. Git hosting metadata identifies
   a repository provider; filesystem observations identify a working copy.
5. Record the selected reader, location and source version with the candidate's
   Evidence. Owner WorkItem.source_baseline may be omitted or null; eligible
   intent revisions can select, change or clear it. For Owner project setup,
   pass the current Management Root to the registration preview. Shared exact
   Source export follows the procedure below.

## Read-only Git helper

AI performs these commands for the user when Git checkout inspection is useful.
Run from the verified Release or installed setup Skill's root directory:

```text
python scripts/acs_source_discovery.py --path <Git-checkout-path> --include-untracked
python scripts/acs_source_discovery.py --ssh-target <authorized-source-host> --path <absolute-Git-checkout-path-on-that-host> --include-untracked
python scripts/acs_source_discovery.py --wsl-distribution <selected-distribution> --path <absolute-Linux-Git-checkout-path> --include-untracked
```

Use `--management-path` for an already known nested Management Root. Available
expectations include `--expected-project-id`, `--expected-root-id`,
`--expected-repository`, `--expected-commit` and the machine binding trio
`--expected-machine-id`, `--expected-account`, `--expected-user-home`.

The helper returns the actual Source machine and account, repository root,
Management Root identities, commit/tree, branch, scoped working-tree observation
and credential-free remote locators. The result is a discovery candidate.
Candidate states distinguish a successful observation, missing location,
identity conflict and unavailable access. Git status uses optional locks disabled
and probing reads only the exact candidate scope. Ordinary directories are
inspected through the machine filesystem tools.

## Shared Source export and recorded views

Shared deployments and their historical reference Profiles retain the exact
Source export and configured provider contract:

The current filesystem Source/CAS provider requires an explicitly admitted
Linux view of the checkout on its provider host. If the working Source and that
provider live on different machines, AI checks the authorized access or Git
synchronization mechanism and its actual revision readback. A synchronized
provider checkout is recorded as a distinct view, with its own host/path and
commit/tree; matching names are insufficient.

Existing SourceBindings are read before registering or refreshing a view. Keep
repository, Root/Route and Scope identity stable, authorize only the required
Source and Git metadata locations, and obtain a new guarded registration preview
for the selected clean commit/tree. Windows Source discovery is supported as
read-only Git inspection; the Source/CAS service itself follows the Linux
deployment contract.

Apply the registration plan only when its host, paths, identities, Source
baseline and admitted provider scope agree. Read back `list_sources` and
`load_project` after the transaction. The project report names the working
checkout, provider view, synchronization status and exact accepted Source
revision. See [project adoption](PROJECT-ADOPTION.md) for the registration
specification and expected plan digest.

Existing captured Source records retain their original repository, Scope,
revision and provenance. Owner archive queries select `source_id` and `revision`
explicitly, with `base_revision` and `target_revision` for `read_diff`.
The Agent reports the actual commit/tree observed for new Review and acceptance
through its selected Git, native or machine reader. Current management documents
load from their registered file location. See [Owner Runtime](OWNER-RUNTIME.md)
for the active Project context and evidence contract.
