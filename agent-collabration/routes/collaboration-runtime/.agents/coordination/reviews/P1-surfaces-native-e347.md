# Runtime Surfaces and native Delivery integration review

Decision: PASS for the frozen Surfaces, operator Delivery command and native
adapter component integrated at
`e3470f34e0812017702afb285e21f7fe6e0df050`. Full authenticated receiver
transport, actual model execution and the P1/P2 Gates remain separate.

## Frozen candidate and integration

The candidate was based on
`3f971237ec9665fe8154dc912e7d241a5969f8bc`. Its reviewed identities are:

- patch SHA-256: `4a7bb6a3bb85a0b28ecb90ccbd083e9030f0586b99f9cde655c971f70052cd1c`;
- manifest SHA-256: `850a3ff20e7062c2ad3c8c6cecab9387e7ce94f0ce12e68e9a26f446fa537b69`;
- `runtime/driver_claim.py` SHA-256: `838f5889475add137f81f55609870eb1d60d9e973c53a137a41934b9ed2b3b42`.

Management applied the exact patch to current formal parent
`346e7c18959ba25cd8e1af891c1ca0182dfe4173`, which already contained the
reviewed Systemd user supervisor. All 25 committed Git blobs match the frozen LF
manifest. The two change sets touched no common source target.

MCP 2.2, CLI and versioned HTTP use one `SurfaceService` and strict command
schema. Authenticated context is supplied only by the configured trusted
boundary. Operator `delivery.scan` is read-only. `delivery.dispatch` records its
own dedup, operation, event and Outbox audit and can resume an unfinished audit
without repeating a completed command. Configuration files use descriptor and
file-identity checks; Windows records birth identity and rejects reparse/final
path replacement, while POSIX uses no-follow descriptors and private modes.

`NativeDeliveryAdapter` freezes the Driver binding, identity, journal and kernel
claim. The journal retains a private owner/witness reservation and exposes a
separately witnessed read descriptor. Linux proves the active FLOCK from
`/proc/self/fdinfo` and open-file-description continuity; Windows uses a retained
sharing reservation and `CompareObjectHandles`. Driver claim acquisition is the
last constructor step and partial acquisition failures release all handles.

Codex empty initial threads are inspected without fabricating native history.
Context-only resume performs no native mutation for an exclusively owned,
unmaterialized thread. A deterministic pre-dispatch callback refusal permits a
later new operation to make its first `turn/start`; an unknown callback outcome
remains uncertain and is never retransmitted.

## Independent review

The first Reviewer found a stale patch, an incorrect Codex first-turn latch,
mutable adapter lineage and Ruff import failures. After those were fixed, it
found that closing and reopening the same claim path could reuse the fd/inode
while a competitor acquired ownership. The final kernel-claim design closed that
case rather than accepting inode identity as ownership.

A second independent Reviewer verified the final frozen inputs and all 25
patch/overlay targets. Its cross-platform probes covered same-fd/same-inode
reopen, public/owner/witness/token substitution, explicit unlock, competing
ownership, token lookup failure and failure after all four handles were
allocated. Every changed or released claim failed closed, every retained claim
blocked a competitor, and controlled cleanup allowed a child process to reclaim
the binding. Probe JSON SHA-256 values are:

- Linux: `e61c74f39c0b8b27176110c5b29c76f6281b779efbe4bcbea1cdcd5bfdb30cb9`;
- Windows: `3357f1b44ee952857b5184b99869b2eee3a8fefd28c75ed62b0da9156306eb24`.

The Reviewer ran **235 passed, 3 Windows-only skipped** on Linux, plus 16 focused
real PostgreSQL, MCP/CLI/HTTP, operator command and native marker/first-turn
cases. Windows ran **152 passed, 37 expected platform skips**, plus 37 focused
passes. Ruff and the locked dependency check passed.

## Formal integrated verification

The exact patch on formal parent `346e7c1` ran in fresh locked environments:

- Linux with actual isolated PostgreSQL and Temporal: **672 passed, 21 skipped
  in 222.01 seconds**; JUnit SHA-256
  `9e1a562adf2472f41d8ef0cc1f05c09eeaad215a756502c47272fb5d33eceae9`;
- Windows: **270 passed, 423 platform/service skips in 71.51 seconds**; JUnit
  SHA-256
  `9b34ac67417540df1332741b9f305e908987895468db80d32ec26faed101cae4`;
- full Runtime/test Ruff and `git diff --check`: PASS.

The final Codex Driver ran actual Codex 0.153.2 through the installed strict
filesystem/network helper and the formal Systemd transient-user-service
supervisor. `spawn`, empty-thread `inspect`, context-only `resume` and verified
termination passed. The recorded RPC methods contain no `turn/start`; the unit
was collected, cgroup members were empty and supervisor environment files were
zero. Evidence JSON SHA-256:
`e9bfece56056eebdc4e27868cbf950bb05399b23e966ea2d6480012b470f9574`.

The final OpenCode adapter ran actual OpenCode 1.18.27 on Windows through the
non-breakaway Job supervisor. Health/schema/config/agent/tool inventory,
session creation, inspection, context resume and termination passed with no
prompt endpoint call and no remaining Job member. Evidence JSON SHA-256:
`7f09d760fe9c39b71ac68127ac3eafba610101ee477bd54c6fa1df9431e04c7a`.

These actual probes deliberately made no model turn. Receiver authorization in
the integrated tests is still an injected trusted callback. Production signed
endpoint bootstrap and remote transport, delayed response projection, real
model output, cross-machine delivery and Gate acceptance must be established by
their own integrated evidence.
