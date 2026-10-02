# Locate an existing project's Source checkout

Project setup begins by discovering the actual checkout and its machine. The
Runtime service host, client host, Git hosting provider and Source checkout
location are separate facts. A project can have several clones with different
branches and revisions.

## Agent discovery sequence

1. Inspect the active project session's directory and containing Git repository.
   Read its Management Root manifest and existing Source state when present.
   With an existing ACS project, read authorized `list_sources` metadata for
   candidate repository identity, revision and location information.
2. Derive candidate paths from that project context, recorded SourceBinding and
   the user's already authorized machine connections. Inspect exact paths and
   parent directories. An SSH alias is an address candidate; the confirmed
   project inspection scope determines whether it may be probed.
3. Run the read-only discovery helper on each relevant candidate. Use the path
   spelling of the machine being inspected. Compare Project/Root identity,
   repository identity, machine/account, commit/tree, branch and working tree.
4. Prefer verified active-session Source evidence. If several copies still match
   and differ materially, show their host/path/revision differences and ask only
   which checkout is intended. If a candidate is inaccessible, report the exact
   missing access or path. A Git hosting URL identifies a repository provider;
   it does not identify a local or remote filesystem checkout.
5. Pass the observed Source and Management paths to the guarded project setup
   preview on that actual host. Preserve existing identity and knowledge. Read
   back setup changes before selecting a clean committed registration baseline.

## Read-only helper

AI performs these commands for the user. Run from the verified Release or the
installed setup Skill's root directory:

```text
python scripts/acs_source_discovery.py --path <project-or-management-path> --include-untracked
python scripts/acs_source_discovery.py --ssh-target <authorized-source-host> --path <absolute-path-on-that-host> --include-untracked
python scripts/acs_source_discovery.py --wsl-distribution <selected-distribution> --path <absolute-Linux-path> --include-untracked
```

Use `--management-path` for an already known nested Management Root. Available
expectations include `--expected-project-id`, `--expected-root-id`,
`--expected-repository`, `--expected-commit` and the machine binding trio
`--expected-machine-id`, `--expected-account`, `--expected-user-home`.

The helper returns the actual Source machine and account, repository root,
Management Root identities, commit/tree, branch, scoped working-tree observation
and credential-free remote locators. It creates no SourceBinding or authority
Grant. Candidate states distinguish a successful observation, missing location,
identity conflict and unavailable access. Git status uses optional locks disabled
and probing reads only the exact candidate scope.

## Register the Source under the Runtime

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
