# Checkpoint migration preservation review

Status: database preservation checks passed for the recorded candidate bytes.
Domain adoption, historical command replay and full P1/P2 remain not_run.

## Inputs and scope

- Source checkout base: `501bdf7cebcba730c7ffc523189f61911e11cc78`.
- Candidate schema SHA-256: `f72c49adffb0c239d8cefe584a20240dffe1b99ad434c76efb45f3e672a22dbc`.
- Candidate schema remains an uncommitted integration input.
- Checkpoint SHA-256: `32249cf981e49c1cbbeef6c21a6e47318cf12b9b130eeeb840808c7b7e10dedb`.
- The checkpoint contains Domain and Temporal tables; no Core, Node, Harness or
  Provider was attached to the new restored copy.

## Direct observations

The copy restored 55 original tables, 20 WorkItems, 27 Domain events and 51
command-journal records. Migration retained 21 identities in
`migrated/verify_legacy_hash` and quarantined 30 records whose command ID
conflicted with their result command ID. Their current command IDs became NULL;
every original field remained in its first migration snapshot. All other
original journal fields and all 54 other original tables stayed unchanged.
Repeating migration left the resulting journal unchanged.

The initial assertion required every live original column to remain unchanged
and rejected the intended quarantine transition. Inspection localized the
difference to those 30 command ID fields. Final verification compared complete
original rows against their snapshots and required every other original value
to remain unchanged.

After verification, the copy was set read-only. A fresh connection reported
`transaction_read_only=on`. The original authority database, checkpoint and
earlier read-only restore archive were preserved.

## Related validation and remaining work

The helper passed 34 unit cases, including vectors from the pinned e55 and 912
hash methods. SQL passed 12 real PostgreSQL rollback scenarios covering malformed
IDs, bad hashes, duplicates, tenant separation, retained current rows, retained
quarantine claims and repeat execution. Independent code review passed after
fixing retained-identity reservation and invalid-hash classification.

`verify_legacy_hash` does not authorize replay. Domain integration must verify
historical hashes and trusted principal provenance, preserve quarantine claims
during new-command admission, and exercise actual adoption and authorized replay
before a sealed integrated candidate can pass its Gate.

Private report: `review-912/migration-checkpoint-54a32f45adf0.json`.
Report SHA-256: `60ac5a9f170964a662fcb01bed0d9bd5b490ddfb4989e074ba841eead3d0e765`.
