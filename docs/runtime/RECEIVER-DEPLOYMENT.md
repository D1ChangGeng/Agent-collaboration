# Authenticated receiver deployment boundary

Runtime schema 1.8 adds the authenticated Node receiver. It does not change the
setup profile or Workspace schema. The P1 receiver is POSIX-only and listens on
the allowlisted loopback/private address stored in
`deployment_connection_refs`; delivery packets never carry a locator.

`acs-receiver --config <path>` loads an owner-owned, single-link, mode-0600 JSON
configuration through a descriptor walk. Every configured path has a uid-owned
mode-0700 final parent. Node/TLS private keys and the SQLite journal are mode
0600. The config contains the only factory reference; the command line cannot
replace it.

The Node-signed registration `config_sha256` is the canonical deployment-policy
digest. It covers the factory module/package SHA, stable callable-code identity,
connection and endpoint binding, authority and Node public-key fingerprints,
private reference path fingerprints, ledger policy, bounds, boot generation and
old-boot isolation reference. The digest excludes its own registration field,
so construction has no hash cycle. Config load and TLS readiness both recompute
the digest exactly.

The callback factory is restricted to the deployment-owned
`runtime_deployment.receiver_p1` product package. Before import, the entrypoint checks the configured
module/package hashes and owner-controlled non-symlink origins. After import and
factory construction, it checks file identity/hash again, verifies the exact
module attribute and callable-code hash, and requires callbacks bound to the
configured policy digest, endpoint and Runtime. Private key and database values
remain references or environment-owned inputs rather than command-line
arguments.

The reviewed bootstrap runs `runtime.receiver_provision` directly from the
verified wheel. A fresh bootstrap environment first installs that wheel and
exposes its own `acs-receiver-provision` console. That installed provisioner
runs pip with `--ignore-installed`, `--no-deps` and a checked JSON install report,
so an identical distribution already present in the bootstrap interpreter
cannot suppress creation of the stage. It validates the wheel code inventory and RECORD, installs into
a staging directory under an owner-mode-0700 parent, rewrites both console
launchers with their private installed site path, removes unhashed bytecode,
updates RECORD, hardens directories/files, fsyncs, and atomically renames the
stage into place. `receiver-install-manifest.json` records the wheel, complete
installed-file map, RECORD, launchers and interpreter path/binary digests.
Postflight invokes the provisioned `acs-receiver --verify-install` with no
source checkout or `PYTHONPATH`. A failed postflight atomically isolates the
result under a non-adoptable `.receiver-failed-*` name and leaves the requested
destination absent.

Each receiver startup verifies every installed distribution file against
RECORD and the install manifest, rejects extra or missing files, checks both
launchers and the current interpreter, then verifies the factory origin and
callable. Host umask is therefore not a trust boundary: provisioning produces
owner-private modes even when invoked under umask 0002.

The receiver binds its socket with TLS 1.3, starts its serving thread and makes
an actual TLS connection to that listener. It remains running only when the
presented certificate fingerprint equals the current Node-signed endpoint
registration. A service supervisor may treat a surviving process after this
self-probe as ready; deployment health checks should also exercise the pinned
TLS endpoint.

For a systemd user transient service, `SystemdUserSupervisor` owns the unit and
cgroup. The deployment sets `KillMode=control-group`, `SendSIGKILL=yes`, bounded
`TasksMax`, `MemoryMax` and `CPUQuota`, and `NoNewPrivileges=yes`, then reads
those properties back. The owner-only config/environment references are passed
through the user manager. Secret values do not appear in `systemd-run` argv,
unit properties, journals, proofs or errors. Termination stops only the fixed
unit and verifies inactive state, an empty cgroup and wrapper exit.

`ReceiverNativeDeliveryBridge` reads the immutable invocation from the local
receiver journal and calls the existing `NativeDeliveryAdapter`. At its native
dispatch callback it reads the already committed PostgreSQL
`runtime_dispatched` receipt; it does not create a second Domain marker. A
missing or changed marker blocks native entry. A missing native ACK remains
uncertain and is reconciled through signed receiver readback.
