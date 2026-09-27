# Source admission and readback review

Decision: PASS for the Linux Git/CAS implementation scope of
`9fadc2d12f9f22787eab6fb2aa2fe6cc85b34755`.
Tree: `840f466edca5966a3879cc0b557464f9605bbe91`.
Parent: `bfb9abbaa564bc78fbe0847dfdef939dd1a58f62`.
Management integration commit: `1d9bb5d7a9b7356f9bc2039587c4d4a1ee566fbe`.
Production Domain authorization and the P1/P2 Gates remain not_run.

## Implementation

The Source service admits an explicitly authorized Git worktree into the local
immutable artifact store and records actual commit, tree, status, file, diff,
untracked-manifest and toolchain identities. The Linux profile pins the system
Git executable, fixes authorized directory objects with open file descriptors,
opens descendants relative to those anchors, rejects links and non-regular
inputs, and applies aggregate file, byte, metadata and object-store bounds.

Git commands consume a private metadata and object snapshot. Repository include,
filter and diff configuration, alternates, replace objects and uncontrolled
global configuration cannot become command authority. Diff generation uses the
already captured non-secret file bytes in a private worktree, so a failed final
consistency check cannot first persist excluded bytes. File content and canonical
Git executable mode are checked again during readback.

Independent review found and reproduced configuration, object-alternate,
directory-replacement, excluded-file, diff-consistency and executable-mode
races before the seal. The final exact hashes closed each reproduced case:

- `runtime/source.py`: `a52a70f119ab2b32f02ed0401bd8e0a3291e5fa9f6f6421f2f8345315918dd62`
- `runtime/source_models.py`: `ed7ebbe7661a92131187fc96f352c93addce730a5caf9ec351e62ab9be0955a3`
- `runtime_tests/test_source.py`: `753d612dc519e2484e78e72d819d8470a7bc4662e8965dbac604554a2efd99c3`

The Reviewer independently ran 33 focused tests and Ruff, then reran its own
readback-mode probe. Decision was PASS for these exact hashes. Earlier rounds
also ran eight boundary probes, two captured-byte consistency probes, admission
mode and literal-pathspec probes against the corresponding corrected candidates.
All probe repositories and contents were synthetic fixtures.

## Integrated verification

A fresh `git archive` of the sealed engineering commit was extracted outside a
Git checkout and bound to the full commit and tree through the test harness
identity variables. With real isolated PostgreSQL and Temporal, the archive ran
**444 passed, 18 skipped in 128.20 seconds**. The skipped set was eight
Windows Job Object tests and ten Docker tests whose pinned image was deliberately
not supplied to that invocation. The same archive then ran those ten Docker
tests with local image ID
`sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b`:
**10 passed in 2.64 seconds**. Combined exact-archive coverage is therefore
454 passing tests with eight Windows-only tests not applicable on Linux.

Private raw evidence is retained under
`/home/changgeng/Agent-collaboration/.omo/review-912/source-9fadc-full/`:

- main pytest log SHA-256: `a2248980408b8faefa7333d77666b7df6ebf7c57428d635ff0ee38c1248c5b0a`
- main JUnit SHA-256: `07d0c0506c8aae6f5015f2c22661abe9f460ec7af5dd51bfe7478f69e1d44424`
- Docker pytest log SHA-256: `c0b0de255384d454785dc181c6ed025fcc74d50f17cf3bffa5094d9fc510ae5c`
- Docker JUnit SHA-256: `bd5fa3ea90f6669cda445da732de33c24d06f6f0e34b454d7e54c8219f702454`

Both engineering and management work branches were pushed and read back from
GitHub at their exact commits. The Linux implementation does not establish a
Windows Source backend, production Domain Grant integration, OS-wide process
containment, or adversarial subprocess-spool quota behavior. Those claims remain
outside this component PASS and must be resolved by their own Gate evidence.
