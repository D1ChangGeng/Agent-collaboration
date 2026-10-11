# Governance decision map

Read access_mode from the installed service. New single-owner installation
selects owner. Shared is an explicit deployment choice and remains the
compatibility interpretation for existing unspecified configuration.
Migration changes trusted configuration and the compatible schema while
preserving identities, deduplication, revocation and historical evidence.
Explicit owner adoption preserves the private credential and original
configuration backup, then clears natural expiry only on active, nonrevoked
records. The installer can apply this adoption to its verified private owner
Root profile; explicit shared configuration retains its choice. This helper
updates Surface/database identity state. Receiver owner/native migration
preserves original profile, credential, keys and Node identity while binding a
new matching process/factory digest to the next Endpoint revision signed with
the existing Node key. Commit that revision before restart and mode/Session
readback. Explicitly revoked records retain their lifecycle state.

For owner admission, verify trusted credential and tenant/principal/Authority,
active service and target objects, explicit revocation, canonical request
identity and expected revisions. Select roles according to work responsibilities
and Harness requirements. Apply the exact candidate and independence checks
when accepting a result.

For shared governance, grant the required Scope, operation, direction, duration
and resources, then apply Policy, Profile and budget rules. Recheck these at
dispatch, retry and protected effects.

Choose an explicit business deadline when the request has a latest useful time.
Owner omission keeps continuous validity. Evaluate a supplied deadline or a
shared expiry against the applicable Authority clock after lock waits and at
the protected boundary. Internal RPC and caller wait timeouts govern their own
durations.

Verify TLS, keys, Node identity, signed receiver state, nonces, generations and
durable command identity independently of business lifetime. OAuth expiry is a
transport credential check. Canonical UTC, wire signatures and historical
hashes retain their recorded values.

A resource Lease is meaningful at the gateway that checks it. Native Harness
execution follows the selected user environment and approval configuration.
Codex interactive requests require an actual native client handler; standard
headless Receiver factory uses its transport's explicit -32601 response.
Keep protection and evidence claims within the boundary actually observed.

See `docs/runtime/TIME-MODEL.md` for explicit time windows and
`docs/runtime/OWNER-RUNTIME.md` for migration and owner semantics.
