# Gate evidence record format

`tools/runtime/validate_gate.py` is an offline completeness and integrity check.
It never executes a runtime scenario, authenticates a producer, grants acceptance
or establishes that a human review occurred. Management must read back the actual
source, resources and outputs before accepting producer claims.

Run it against a record and a containing evidence directory:

```text
python tools/runtime/validate_gate.py path/to/P1.json --evidence-root path/to/evidence --require-passed
python -m unittest discover -s tools/runtime/tests -v
```

The initial Route records deliberately retain `not_run`. They can pass structural
validation but fail `--require-passed`. Synthetic fixtures in the checker tests
exercise rejection behavior and are never Runtime Gate evidence.

## Records and references

The adopted scenario set and required binding fields are in
[gate-contract.json](gate-contract.json). A record uses `acs-gate-record/1`,
the exact contract revision, Gate ID, status and full integrated Git baseline.
Passing scenarios must cover the exact mandatory scenario set without duplicates.
The Profile binds machines, nodes, OS, Core, Provider, Driver, Harness, database,
protocol, Credential Scope, Policy, Direction and expiry. `binding.os` maps
Machine IDs to pinned OS versions and must match their observations.

Evidence references are objects with `path` and lowercase SHA-256 `sha256`.
Paths are relative to the supplied evidence root. Absolute paths, traversal and
symlink references are rejected. All referenced bytes must exist and match.

`binding_sha256` is SHA-256 of UTF-8 JSON serialization of the binding using
sorted keys and compact separators. Passing scenarios carry that digest, the
same `source_baseline`, `evidence_class=directly_verified`,
`evidence_state=complete`, `observed_at` and `expires_at` with timezones.
They record command/operation/message/event IDs, observer, owner and unresolved
items. Raw output, receipts, fault injection and read-backs use nonempty evidence
reference lists. Unsupported self-declared `not_applicable` does not remove a
required layer. For a denial scenario, preserve the actual rejection and
read-back showing that no protected effect occurred.

## Machine and Session observations

The binding's `machine_evidence` maps each Machine ID to an
`acs-machine-observation/1` JSON reference. Its fields bind `machine_id`,
`node_id`, `profile`, `host_fingerprint`, `os`, observation/expiry times,
evidence class and a raw evidence reference. P2 requires observations of distinct
machines; creating two arbitrary IDs cannot replace host evidence.

P2 additionally carries `session_evidence` references to
`acs-session-observation/1` records. Each binds `session_id`, `machine_id`,
`node_id`, `profile`, `harness`, `harness_version`, `driver_version`,
observation/expiry times, evidence class and raw evidence. Keep real Machine/Node
and Harness associations visible. A native session receipt only proves its
observation layer, not the Collaboration Runtime loop.

## Prerequisites and review

Each prerequisite is a digest-pinned record, not just an outer `status=passed`.
The validator reads prerequisite contents recursively and rejects cycles,
unpassed prerequisites and incompatible baselines or Profiles. Prerequisite
observations must precede dependent Gate execution, and independent review must
follow the scenarios it reviews. `BOOTSTRAP` pins
its historical setup `source_baseline`, contract revision, expiry and
`preservation_inventory` reference; its actual audit report, checks and logs
must validate. A historical setup baseline is not a Runtime implementation
baseline.

`review.evidence` points to an `acs-gate-review/1` JSON record binding Gate,
contract revision, Profile, source baseline, binding digest, Engineer, Reviewer,
decision, unresolved items, timestamps and raw review evidence. The Reviewer
must differ from the Engineer. Independent read-back establishes whether that
assertion is true; JSON alone cannot establish actor identity.

P2 review includes the product owner's recorded decision. `supported` additionally
requires all five evidence layers from the adopted contract. Each layer reference
points to an `acs-support-layer/1` JSON record with `layer`, `gate`, `profile`,
`source_baseline`, `binding_sha256`, `contract_revision`, `observed_at`,
`expires_at` and a raw `evidence` reference. Passing this checker does not supply
any missing user authorization or permit a release.

## Evidence storage

Raw operation evidence is private by default and may contain host paths or
execution details. Keep it in ignored storage or an authorized evidence store.
Before publication, curate an auditable bundle under the named data policy and
verify the final bytes again. Source commit, publication result, actual read-back
and AcceptedStateRevision remain separate records.
