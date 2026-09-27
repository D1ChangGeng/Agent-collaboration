# P1 restart child environment review

Decision: PASS for the two-file probe correction on base
`3c2ee29728f92699d131ebc17b13f351f7639de5`. The formal P1 Gate remains
blocked. This review does not accept the original failed run as intact evidence.

The sealed candidate archive SHA-256 is
`24f53cc985414f3d7097b92ad40e14ec6963b6c20d9d8bd9aa51b32e71138409`,
manifest SHA-256 is
`680dbc19464ed931aadd3fc122c81d51514cc6294bcc8de9372c06ea778cccf3`,
and patch SHA-256 is
`7b43ba1cb7e1b119e6c03c785df080383b2968a2272c8b4e006931c50b9dbcf0`.
Both applied LF target hashes matched the manifest and the two-file staged tree
was `34c9a560105ee8f392c53d9a5903dd5dea7c3be4`.

The original 3c Gate run completed four scenarios but blocked Core, Node and
Provider restart when child Python processes could not import the reviewed
runtime dependencies. The fix forwards `PYTHONPATH` only when the sandbox has
the exact `/run/acs-p1/runtime` binding and the value is precisely its
read-only `site` directory. Six wrong-path variants were independently
rejected. The independent reviewer applied the patch to the exact base and
ran a fresh private Gate: seven scenarios and 42 evidence commands passed with
matching run/source/operation/message identities; 11 remain `NOT_RUN`, so the
overall Gate was blocked. Runner HMAC audit passed, dedicated PostgreSQL
schemas were cleaned, tools tests reported 109 passed and 14 platform skips,
and changed-target Ruff passed.

The original failed run is historical, compromised evidence. Before a review
audit, its state SHA-256 was
`1caab1a71947f91a0b66d0df8ee79ca9f239571c0a7086f4d570f6e2705584e5`,
with four passed, three blocked, 11 not run and 24 command outputs. The
reviewer's `audit` call detected a source-inventory change and, by the runner's
write behavior, appended `source-mutation.json` SHA-256
`01d8c664e385baa9acd354c64aac8dc5d104037c3d86af992aac17ca951be85a`.
The current state SHA-256 is
`41269ab5ebb5bcd67a1683fd6d7bcd75c61209ba6352050eb930135edd6c56d8`;
its HMAC is valid and `source_compromised=true`. The old RUN-MANIFEST was not
rewritten and no longer hashes the current state file. The 24 raw command
references still match their recorded digests. No byte-for-byte pre-audit
state backup exists, so the old state was not reconstructed or overwritten.

The fresh fixed candidate run and the final integrated source require their
own exact source read-back. Separately, an independent security review found
the P1 runner's raw user-bus sandbox mount grants broader host control than
the Gate profile permits. That isolation issue remains a Gate blocker and is
outside this child-environment correction.
