# Linux strict sandbox helper review and deployment

Decision: PASS for the dedicated helper package and its actual host postflight.
This does not by itself pass the Codex Driver or P1 Gate.

## Package

The package is tracked at `tools/runtime/acs-bwrap-package/`. It installs only:

- `/opt/acs/codex-sandbox/bin/bwrap`, root-owned, runtime group, mode 0750;
- `/etc/apparmor.d/acs-bwrap-userns`, root-owned, mode 0644;
- `/opt/acs/codex-sandbox/manifest.json`, root-owned, mode 0600;
- AppArmor profiles `acs_bwrap` and `acs_unpriv_bwrap`.

The package never changes global sysctls, `/usr/bin/bwrap`, a distribution
profile, services or Node configuration. It refuses links, writable ancestors,
foreign target files, digest/mode/owner drift and live or uninspectable package
capacity. Uninstall removes only manifest-proven resources after a stopped
capacity check.

Reviewed identities:

- package archive SHA-256: `0710dc939858efa671189b24d52b4620e62aeaeba898a25e7657d4b68add43ef`
- `manage.py` SHA-256: `0091b0399cf9b2f1e849bfac310fed8dd53ad8edbd19eaf841f2edef5d0bb1fc`
- installed helper SHA-256: `52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712`
- dedicated profile SHA-256: `7b2beb270c7218b549883337f53cbdca903d4e93803704af42788f63f93583a1`

Windows ran 53 guard tests with seven Linux-only file-descriptor cases skipped.
Linux ran all 60 tests. The tests include real bounded file replacement/growth
cases; UID, capability, namespace and mount outcomes in unit tests remain
explicit fixtures. Ruff passed after the executable scripts were deployed with
their required executable mode.

## Actual installation and postflight

The normal SSH account had no applicable sudo rule. The already authorized
local Docker daemon supplied a root process; `nsenter` moved that process into
PID 1's mount, user, IPC, network and PID namespaces before running the reviewed
package from root-owned `/root/acs-bwrap-package/`.

An earlier apply inside the Docker container namespace was rejected by the
package's own user-namespace postflight. It automatically removed its new
helper, profile and manifest; a readback confirmed all three absent and both
global user-namespace sysctls unchanged. No failed-install state was adopted.

The host-namespace install and a separate repeat `verify --apply` both passed.
Actual readback established:

- helper `root:changgeng` 0750, profile `root:root` 0644 and manifest
  `root:root` 0600 with exact hashes;
- both dedicated AppArmor profiles loaded in `enforce` mode;
- runtime UID/GID 1005/1005 and `CapEff=0`, `CapPrm=0`;
- a distinct network namespace with only loopback and no non-loopback route;
- a host-writable control for that UID;
- readonly bind write rejected with errno 30 while the host sentinel remained;
- the otherwise identical writable bind changed the host sentinel and made the
  readonly verifier exit with the dedicated code 42.

Private repeat-verification JSON is retained at
`/home/changgeng/Agent-collaboration/.omo/review-912/admin-helper-installed/verify.json`,
SHA-256 `2434c9e2de06058ba5aad8ff4910fc2df21970fc7055952a0f70e7ab41e5773c`.

The explicit rollback entry remains:

```sh
/usr/bin/python3 /root/acs-bwrap-package/manage.py uninstall --apply --capacity-stopped
```

It must be run from a host-root context after restoring the Node PATH and proving
this package's capacity stopped. Actual Codex strict-profile conformance remains
a separate Driver test. The first post-install no-model probe created a native
thread successfully, then exposed a Driver incompatibility with App Server's
unmaterialized-thread read behavior; that Driver issue is not relabelled as a
helper failure or a Gate pass.
