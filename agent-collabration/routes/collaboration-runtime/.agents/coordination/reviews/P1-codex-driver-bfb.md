# Native Codex protocol Driver review

Decision: PASS for the implementation/wire scope of
`bfb9abbaa564bc78fbe0847dfdef939dd1a58f62`.
Tree: `86df13bae5cc64357ef7108960f5f510792dd55a`.
Parent: `3dcf94708832876084949720ca086a60e6d11307`.
Actual model lifecycle and full P1/P2 remain not_run.

## Implementation

The public CodexDriver now selects the native App Server implementation.
The endpoint forwarding adapter remains explicitly named and reports only its
implemented invoke action. It is not native-Harness evidence.

The Driver uses bounded bidirectional JSONL, persistent operation/RPC intent,
current authorization before execution and replay, immutable Node/boot/Runtime/
Attempt binding, exact-turn cancellation, native message/content correlation and
readback. Ambiguous invoke acknowledgements do not cause another turn/start.
Process-tree termination requires matching verified Supervisor evidence.

Independent socket probes exposed two issues, fixed before this seal: a late ACK
could resolve a reused request ID, and reconciliation could overwrite an already
acknowledged native turn. IDs are now reserved for the connection lifetime within
an explicit budget. Reconciliation preserves prior turn identity and its original
acknowledgement. The independent Reviewer reran all 30 wire tests and approved
the corrected implementation scope.

## Verification

The actual integrated package passed 37 protocol/adapter tests. A fresh exact
source snapshot with PostgreSQL, Temporal and configured Docker returned
**421 passed, 8 Windows-only tests skipped, 134.78 seconds**. Ruff passed.
The installed Linux 0.153.2 generated protocol schema is included as a versioned
test input. Raw full-suite SHA-256:
`c04c84727211e47d2656fca4f66884d49f347b0f09398cde060b89c5ad4c8b97`.
Private raw outputs and JUnit are retained under `review-bfb/`.

The earlier actual Linux 0.153.2 probe initialized successfully but strict
thread/start failed at the host bwrap/AppArmor boundary. The actual Windows
0.152.1 probe initialized successfully and reported sandbox readiness
updateRequired; its preflight gate sent no thread/start or setup request.
Each probe's exact source hashes remain in its private evidence; they are not
relabelled as a real execution of this later sealed Driver. Both probes used
fresh owned capacity and completed their scoped process cleanup. No model was
invoked. Synthetic peers remain explicitly labelled in wire evidence.

The reviewed dedicated Linux helper still requires an available administrator
execution context before real strict-profile conformance can resume. Windows
sandbox readiness also requires its own deployment verification. Lost spawn or
session-create ACK adoption, persistent Supervisor takeover, OpenCode integration
and full cross-machine/Harness loops remain separate work.
