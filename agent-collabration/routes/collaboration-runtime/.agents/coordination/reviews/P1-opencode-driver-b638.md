# Native OpenCode HTTP Driver review

Decision: PASS for the implementation and no-model lifecycle scope of
`b63884e818037bc27e05718b95b86a74a750e24b`.
Tree: `d1611c30a06372c6621d3bc20efd7b453c62c016`.
Parent: `9fadc2d12f9f22787eab6fb2aa2fe6cc85b34755`.
Management integration commit: `3e43b9d628aefd7b351097e82fd0577672f36a45`.
Actual model execution and the P1/P2 Gates remain not_run.

## Implementation

The public OpenCode Driver now uses the native local HTTP implementation. Its
launch profile pins OpenCode version, executable, fixed OpenAPI, configuration,
model, agent and isolated state roots. Spawn requires exclusive Supervisor
ownership and a verified IPv4 loopback listener. Attach is read-only. Mutations
use bounded method/path/body rules, no proxy or redirect behavior, per-capacity
Basic authentication, immutable Node/boot/Runtime/Attempt binding and exact
session/message readback.

HTTP 204 records scheduling only. A native acknowledgement requires the exact
authorized user message. Terminal response collection correlates the assistant
message to that user message; session-only cancellation first proves the active
message and terminal result. Termination requires matching Supervisor identity,
root exit and an empty remaining process set.

Independent review reproduced three defects before the seal: a live exclusively
owned process could release its Driver claim, the effective agent could append a
tool allow after the global deny, and preparation intent could be mistaken for
entry into an external mutation. The final Driver rejects live-owner detach,
reads the actual native tool inventory, evaluates ordered rules after the final
global deny, and records distinct process/HTTP dispatch markers after the last
authorization check. The Reviewer's original five negative cases then passed.

Final source hashes:

- `runtime/opencode_driver.py`: `09275f22f25b23ae68e83182e8d745e7b77f2719296b8faa549549aae41b491f`
- `runtime/opencode_http.py`: `05c1cf91755642213fef1bee399a71e4f44da1bb769ac90f98765e1042de1c1e`
- `runtime/drivers.py`: `712ef79bf488cbc293cb63488aa63dafa680dcc19cce4df1dc5925252fe50d92`
- `runtime_tests/test_opencode_driver.py`: `85a348707e2c704b5db365c455ca926deb6820898d53f7d3b6752cedef43811a`
- fixed OpenAPI: `6ea6c82efbff42d0131a0a72ac2d8ddcec36b0ae31547bf1424dbb1b87b729d5`

The independent final run was **37 passed in 16.63 seconds**, plus the
Reviewer's five former counterexamples at **5 passed in 1.84 seconds**; Ruff
passed. Windows repeated the actual OpenCode 1.18.27 no-model lifecycle on the
same final Driver: spawn, health/OpenAPI/config/agent/tool-inventory validation,
session creation, inspect, context-only resume, inspect, verified Job Object
termination and detach. It sent no prompt, abort or model request. Evidence JSON
SHA-256 is `74711ea0f7ca510c4ca06cacb694e6fbdc1c7b2f036457229cead925a1229194`;
Driver journal SHA-256 is
`7961f2df58fed3bde1b512ca92dfabf7c91f32f7b77d670ba8fa815b355afb30`.
Termination readback reported no remaining process IDs; a separate process query
found neither recorded process ID.

## Integrated verification

A fresh `git archive` of the sealed engineering commit, bound to its exact
commit/tree and run with real isolated PostgreSQL, Temporal and the pinned local
Docker image, completed **491 passed, 8 Windows-only tests skipped in 159.14
seconds**. Private evidence is retained under
`/home/changgeng/Agent-collaboration/.omo/review-912/opencode-b638-full/`:

- pytest log SHA-256: `4418298317a7e4edecd72c9b05719bb25400b37b345cc828d920a7d6ac8c303d`
- JUnit SHA-256: `5bde2c9dc152344fa4676342042b525dd95841a9b3c8246114f9bbf88d7959b9`

Both engineering and management work branches were pushed and read back from
GitHub. PASS covers the reviewed Driver protocol and the Windows native no-model
lifecycle. It does not establish a real model response, Linux OpenCode
containment, production Domain/Delivery integration, cross-machine transport or
the Codex-to-OpenCode P2 loop.
