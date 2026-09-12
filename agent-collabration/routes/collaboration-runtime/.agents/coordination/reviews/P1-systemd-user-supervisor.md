# Linux systemd user supervisor review

Decision: PASS for non-root Linux transient user-service containment and the
formal Runtime integration. This does not by itself pass the Codex Driver or P1
Gate.

## Implementation and identity

`SystemdUserSupervisor` launches one exclusively owned native process tree in
one generated `systemd --user` transient service. It pins the unit name,
InvocationID, ControlGroup, root process birth identity and policy readback. The
unit uses `Type=exec`, `ExitType=cgroup`, `KillMode=control-group`, bounded
TasksMax/MemoryMax/CPUQuota, `NoNewPrivileges`, `RestrictSUIDSGID`,
`LockPersonality`, mode 0077 and a bounded stop timeout. Termination is accepted
only after the owned cgroup is empty and the transport wrapper has exited.

Target environment values are written to a per-user runtime file with a private
directory, mode 0600, no-follow/exclusive creation and identity checks. Only the
EnvironmentFile path and minimal D-Bus/runtime variables reach the
`systemd-run` wrapper. The file is removed immediately after unit admission and
also on launch failure. Launch and close share a lifecycle lock; close retires
all known records best-effort before reporting failures.

Reviewed candidate archive SHA-256:
`84f7e9431179c6c7c3ba671e02eff88c9cfe25061a170f429746abcd644c4519`.
Formal integration hashes:

- `runtime/systemd_supervisor.py`: `55a3b40c5b864de7eed01b11d544ce7a5aa063ac7b97b85196b82b357c4119e1`
- `runtime/supervisor.py`: `84c9ca3b06bdc3f8199bcab1b95d44d6381d29d6dce422fd0e702f601dc9645d`
- `runtime/__init__.py`: `8e920161c9e1289caa5f1aa4512afde936452320057e7796a8a87c8a9af9014b`
- `runtime_tests/test_systemd_supervisor.py`: `a71fdcf31dd29539a4cb6a4c193abe1abbdc7e369f0b583db698ca32a9bde052`
- `runtime_tests/systemd_jsonl_fixture.py`: `3f234c7c1fe24a041123d9c4ef6be8a90e138664caa4c260920b2e85d6eee8a0`

The formal test differs from the sealed candidate only in its package import,
fixture filename and Ruff-compatible import order. The implementation source
and fixture bytes retain the reviewed hashes.

## Independent and integrated verification

The author ran 25 real systemd lifecycle, identity, cgroup, secret-isolation,
failure-cleanup and launch/close-race tests on Ubuntu 24.04 with systemd 255.
An independent Reviewer first found and reproduced target environment exposure
to the wrapper, a launch/close race and close aborting after one corrupt record.
After repair it independently repeated the sealed archive: 25/25 passed, four
independent lifecycle groups passed, and zero candidate units, environment files
or processes remained. The final review decision was PASS for this component.

The formal integration was applied to a detached worktree at exact base
`3f971237ec9665fe8154dc912e7d241a5969f8bc`. A fresh locked environment ran all
25 systemd tests and Ruff successfully. The first whole-suite run produced one
intermittent Source secret-path failure while 567 tests passed; the same case
immediately passed alone. A second whole-suite run in the worktree's own
environment completed **568 passed, 18 skipped in 185.50 seconds**. JUnit
SHA-256 is
`ccc692eac08d3b963f5410737707ccc1144fb2e74bf3a241413fc364bf85d587`.

## Actual Codex containment probe

The integrated supervisor launched the pinned Codex 0.153.2 native executable,
performed App Server `initialize`/`initialized` only and did not start a thread
or model turn. Readback proved a dedicated user service with four live cgroup
members and the complete pinned policy. Termination proved the cgroup empty,
the wrapper exited and the transient unit collected. Subsequent host readback
found zero `acs-*.service` units and zero supervisor environment files.

The evidence JSON SHA-256 is
`ea2cdbc668c91d6017903bdb3bc61400df718a20e2fb42c8e17ddc92746443f3`,
retained privately at
`/home/changgeng/Agent-collaboration/.omo/review-912/systemd-integration-3f97/codex-no-model.json`.

This PASS covers the user-service process-tree lifecycle on the reviewed Linux
host. The separately installed strict filesystem/network helper, full native
Driver lifecycle, authenticated Delivery composition, real model work and
cross-machine P1/P2 Gates remain separate acceptance scopes.
