# OpenCode staged readback and actual model review

Decision: PASS for the staged native-message readback correction integrated at
`75c3f1f3e458cf7b2e48c2d6334002a30a37466f`. The actual model evidence is
bounded to the reviewed revision-1 success path described below; P1/P2 remain
not_run.

## Problem and correction

Actual OpenCode 1.18.27 can make a newly scheduled user message visible before
its text part is committed. The previous Driver treated exact message metadata
with `parts=[]` as an identity violation. In the measured run it dispatched one
`prompt_async`, observed one user-message row and zero part rows, then stopped
before collecting the response.

The correction treats only an empty list with an otherwise exact message,
session, Agent and model identity as a bounded incomplete observation. It keeps
the existing readback window and never resends the prompt. Non-list containers,
non-mapping elements, multiple parts, nonempty field differences and
cross-session identity remain controlled `DriverRejected` outcomes. Both the
single-message readback and full history inspection validate container and
element types before accessing fields.

Frozen revision-2 identities:

- base: `fac4466c2299120f7df3e9b62cec98672fccddc1`;
- patch SHA-256: `aef14d35b5f2fc0a99a6eec90dc81853125de057ca2e6fa0767285e7c206d0e3`;
- manifest SHA-256: `00c1c2f392bd0139c617d94b8350ac6a0476c0bb123e3088b205e95da091ba30`;
- final `runtime/opencode_driver.py` SHA-256:
  `cbc7104902a1c0e68d440c6410787ca253a31738e026c08c8752b7c502608505`;
- race-test SHA-256:
  `9ce7fd8f86c435a85f728f2d50e75f48cf1f4a00c12982b2c3756214db567178`.

## Independent and integrated verification

The first independent review found that scalar part values raised an unchecked
`AttributeError`; revision 2 added type guards to both affected paths. The final
Reviewer independently applied the two-target patch and ran:

- Windows: **65 passed in 42.95 seconds**;
- Linux: **81 passed in 54.71 seconds**;
- Ruff: PASS on both systems.

Its cases covered exact empty-parts pending state, bounded exhaustion,
same-operation replay without retransmission, late reconcile/collect, scalar,
mixed, null, string and mapping containers, duplicated and wrong nonempty parts,
and both Driver inspection paths. Every malformed value produced a controlled
Driver rejection rather than an implementation exception.

Management applied the exact patch to current formal base `fac4466` and ran the
complete Linux Runtime suite with real isolated PostgreSQL and Temporal:
**700 passed, 21 skipped in 240.09 seconds**. JUnit SHA-256:
`e589269236f4ac5d7a1fe981a73ac2175d9ab088627a3c914fefa5717a676340`.
Fresh Windows focused integration and Ruff also passed.

## Actual OpenCode model turn

Revision 1 ran an actual Windows OpenCode 1.18.27 turn using the public
`opencode/big-pickle` model, an isolated workspace and configuration, no imported
credential, all native permissions denied and native delegation disabled. The
run observed one incomplete message window, then exact scheduling readback and a
terminal response. The assistant text was exactly `ACS_P1_OPENCODE_OK`; one
`prompt_async` was dispatched, no tool part was returned, and the Driver journal
contains one terminal readback. The Windows Job proof reports `verified=true`,
`root_exited=true`, no remaining/pending process, and no breakaway.

- evidence JSON SHA-256:
  `e79fb88038926fc301627ecf189ede00d3080a2709a0579647dfdc1928baf167`;
- Driver journal SHA-256:
  `f36088d8d4ad087e92db6392c7bdd90c3383404d68e679fd548725ce4b71f8b5`;
- measured revision-1 Driver SHA-256:
  `4ca15d65d152f188328f2ffdb0d039dbd1835e28ae993cb1fc784d38cb63518b`.

Revision 2 changes only the two container/element type guards, and the Reviewer
confirmed every part in the successful actual trace is a mapping. A separate
revision-2 native no-model smoke passed with zero prompt calls and verified Job
cleanup. This establishes that the actual model success exercises the unchanged
revision-2 path, while retaining the exact implementation hash distinction.

This component evidence does not establish signed remote receiver transport,
Domain receipt projection, late-response recovery through Node/PostgreSQL,
cross-machine operation or a Gate decision.
