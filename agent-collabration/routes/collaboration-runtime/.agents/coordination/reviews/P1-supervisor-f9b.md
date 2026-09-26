# Owned-process supervision review

Decision: PASS for component `f9bffec290e7804f930e794b7e30bccab87d853d`.
Tree: `55d1d321e40eda29d54c595b8fa1548f49d4873f`.
Parent: `dd0e27dd603632575202ddaa753b4764d572408d`.
Full P1/P2 and complete Harness sandbox conformance remain not_run.

## Implemented boundary

Windows creates an unnamed Job, configures kill-on-close and process limits,
creates the native root suspended, checks its actual executable image and Job
membership, then resumes it. It retains observed member handles and creation
identities. A member removed from the Job list but not yet signaled remains a
pending exit; termination returns zero residuals only after exit confirmation.

Linux uses an explicitly configured, already-present image under Docker. Before
start it verifies read-only root, non-root identity, private namespaces, capability
removal, no-new-privileges, resource limits, exact bind mounts and bounded tmpfs.
Only regular prepared files/directories can be bound, with identity checked again
before start. Lifecycle mutations check original container ID, label, StartedAt
and process birth. A restarted container cannot be killed using its old handle.
Node must exclusively control that capacity's Docker lifecycle.

## Review and direct evidence

Independent review closed three Linux defects: stale-handle termination after
container restart, special-file binds, and incomplete tmpfs readback. A subsequent
Windows review checked native image admission and the observed-process handle
exit barrier. Both scoped reviews passed the final source.

Management tested the actual Windows package with the project's Python 3.13.15
venv: **8 passed, 10 Linux cases skipped**. The venv launcher creates an inner Job;
a successful breakaway request can still remain in the outer Job. Tests therefore
check actual outer membership, process creation identity and exit through held
handles. Native Codex 0.152.1 direct executable launch was also exercised. This
is an executable/containment test, not a model lifecycle test.

The actual Linux package returned **10 passed, 8 Windows cases skipped**. It covers
setsid descendants, old-handle rejection on real container restart, special bind
sources and nine actual tmpfs configuration variants rejected before start.
Probe containers were removed and the original running-container set was preserved.

A fresh exact-commit Linux snapshot with real PostgreSQL, Temporal and configured
Docker returned **357 passed, 8 Windows-only cases skipped, 98.33 seconds**.
Ruff passed. Full-suite raw SHA-256:
`fbf31764475268618a4d4edae4dcd8b0be55e15b49ff3265a9aff8d3b44f9a9f`.
Private source-bound outputs and JUnit are retained under `review-supervisor/`.

## Remaining scope

Jobs do not independently enforce filesystem, credentials or external-broker
isolation. The tested Docker image is a small offline test image; it is not a
Codex/OpenCode deployment. Persisting and recovering Supervisor handles across
Node restart requires a separate adoption/reconciliation mechanism. Missing
ownership or process evidence cannot authorize replacement. No existing service
or global host security policy was changed by these tests.
