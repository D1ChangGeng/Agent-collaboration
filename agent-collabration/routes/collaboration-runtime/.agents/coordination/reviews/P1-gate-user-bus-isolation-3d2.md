# P1 Gate user-bus isolation review

Decision: PASS for the runner isolation correction at
`3d2a9d71c19698f54d98f6690f0dcf539e17b165` (tree
`69d43c2e27d2fb81912817d6bbed93e2188e7332`). The P1 Gate remains
`NOT_RUN` as a complete profile.

The candidate bundle SHA-256 was
`69d5c41a0c6b05c911c32aa98752118a27fd5863f4dc798db21dd4419955e150`.
The sandbox now receives the reviewed runtime profile and dependencies, plus
a read-only `host-os.json` for OS evidence. The host runner makes one fixed
user-manager observation, discards its environment output, and binds the
attestation to run, source commit/tree, command, binding digest, UID and
SHA-256. The user-bus socket and its parent descriptor stay in the trusted
runner process; neither appears in the sandbox mount arguments or inherited
descriptor set.

Independent Linux tests reported 50 passed and one platform skip, with Ruff
passing. A real bwrap guest confirmed the bus path was absent while the
read-only host attestation was accessible. A separate reviewer found that a
same-byte permission change to `host-os.json` initially escaped final audit.
The corrected final audit requires an owner-private parent, regular file,
current UID, mode `0600` and one hard link; an independent `0644` counterexample
now fails. Older OS results without the attestation cannot pass this audit.

On an isolated exact-source run
`p1-run-0f59d4039ceb0c6937c0679ed09ea4ea`, the Domain transaction scenario
passed all six evidence kinds. Its host OS attestation SHA-256 was
`6e3feff170045842bc4b9117e897f7ad96a7fd3f22acf41dc083da1dd78b91e2`;
its run/source/command/UID and `0600` file identity were read back. The run
manifest matched its files, no test credential appeared in evidence, and the
probe schema and test units were cleared. The other 17 scenarios remained
`NOT_RUN` in that run, so its overall status was blocked. Node and Provider
restart integration was separately exercised on the preceding candidate with
unchanged probe source, but was not promoted by this single-scenario run.

The existing probe has a separate Machine identity defect: its Gate result
uses the physical Machine ID while Node SQLite still uses a scenario-derived
Machine ID. In the independent Domain run those IDs were
`machine-ad6cfb7cba50a2c4c009` and `machine-dac08e7fdd33cd2bd4adc271`.
The shared probe needs a single verified Machine binding and a fresh integrated
Gate run before P1 evidence can advance.
