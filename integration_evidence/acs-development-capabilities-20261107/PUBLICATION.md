# ACS P0/P1/P2 source delivery

This delivery commits the completed Core Runtime, SDK, tests, adopted contracts,
the two contract packages used by the tests, and the reviewed development evidence
to `codex/core-cleanup`. The receiving remote ref is
`origin/codex/core-cleanup`. No deployment or release tag is part of this action.

The containing Git commit identifies the delivered source. The verification base
remains `19d7881d49ee887315c54c5bc02e0cc424061376`; `source-state.json`, the
recorded dirty-tree digest and the uncommitted-state descriptions in the test
reports are historical measurements taken before this delivery. They are not
rewritten to claim tests ran after the commit.

The final service integration passed76 tests with0 failures/skips; SDK210 tests,
strict TypeScript, contract exports and the191-file source/wheel/temporary-install
comparison passed. `development-capabilities.json` maps all25 change items,
40 requirements,35 operations and30 UI/source contracts. Actual Native/Orca
qualification remains separately recorded in `qualification-matrix.json`.

Immutable contract packages and raw evidence use scoped Git attributes so their
recorded bytes and checksums survive checkout. `publication-snapshot.json`
records the selected product subtrees, tested working-file hashes and staged
Git blob identities, including any line-ending normalization.
The only product-source cleanup after the final acceptance was one trailing
space outside a SQL string literal; Python AST equivalence was verified. That
formatting delta and its before/after hashes are recorded in the snapshot.

The original local acceptance helpers are archived under `reproducers/`.
Restore each helper to the `.tmp/` location recorded in its header before using
the original commands. They require the explicitly named isolated database and
local development tool paths recorded in the reports; they never select a
production database or send to an existing contact.

Earlier Client research/archives, experimental worktrees and unrelated local
materials remain in the workspace. Historical evidence included here retains
its original source and qualification scope. A different clone must explicitly
fetch this branch and verify its checkout before continuing; push does not pull
or deploy another clone.
