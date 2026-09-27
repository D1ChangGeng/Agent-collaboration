# P1 Node and Provider restart harness review

Decision: PASS for integrating the two additional **runnable probe adapters**
on the `3d140d193a92b6da4c4b7753f41b91f24bcaa299` source baseline. This
decision does not mark either formal Gate scenario PASS. Seven of 18 P1 probe
scenarios now have commands; the other 11 remain `NOT_RUN`.

The author sealed archive SHA-256
`099a18e3f10a51f80e07749d7a22ab2d7eab49bce527f206fb2fefeef2356ce8`,
manifest SHA-256
`6d06a639e92f8c677d3d9a643ac5b9783910c6f2502da343ad02e8cc04c547e8`,
and overlay patch SHA-256
`2dc2382c79da1e241e22d376e65bed293864173472ce3dfab32f336fe9dcaaa8`.
All four target LF hashes matched the manifest after applying the patch to the
formal baseline. The staged Git tree was
`e5bc4eb95a562f20a210d117ee96c6c298041f25`.

The independent reviewer applied the frozen patch to both its exact `6b6927d`
base and the then-current `3d140d1` source. In a private Linux test profile,
the reviewer observed 12/12 six-kind readbacks across Node and Provider
restart. Node replacement used a new boot over the same SQLite journal,
selection revisions 1 to 2, and rejected old-boot reactivation. Provider
recovery stopped the first Worker at exit 84 and continued the original
prepared attempt in the same Temporal Workflow/Run with a replacement Worker.
Both `message_only` scenarios made zero Driver model calls. Four context/mode
tamper cases failed closed; private evidence had no secret hits; PostgreSQL
probe schema residue was zero. The review result is retained privately at
`/home/changgeng/Agent-collaboration/.omo/review-912/p1-r4-independent-review-result.json`
with SHA-256
`37946d668cd9061780d2d50055f1d6066132d118095e210d23ad27b410ce9ee6`.

Linux focused tests reported 26 passed and one platform skip; the full tools
pytest log reported 121 passed and one skip. Its outer SSH wrapper returned 1
because of command escaping, so the pytest log, rather than that wrapper exit,
is the test evidence. The independent Windows applied copy reported four passed
and 23 platform skips. Ruff passed. The final formal checkout repeated the
four-target LF hash check, `git diff --check`, Windows focused tests and Ruff.

The probes require an independently reviewed plan, a fresh real Gate run on
the named Machine, and separately signed/read-back Gate evidence before the
formal scenario status can change. No Codex or OpenCode model lifecycle evidence
is claimed by these two restart adapters.
