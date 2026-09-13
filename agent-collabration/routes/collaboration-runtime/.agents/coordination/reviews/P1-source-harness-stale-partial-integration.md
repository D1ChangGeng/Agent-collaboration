# P1 Source, Harness response, Stale baseline and Partial artifact review

Decision: `PASS_BOUNDED` for the four-component integration candidate based
on formal working-branch commit `dab8e9670357aba8786451a6a6f52f6727dde72d`.
The code integration at `98e6fedefc3bb2bd1747080984f086fbe1746f6d`
has tree `a15184f49f5dbb6cb7802f4f10eeaae7c1d91918`. The follow-up probe
documentation changes no executable source. This review authorizes bounded
source integration, not P1 acceptance or a formal Gate status change.

The Source admission fix comes from isolated candidate `44561c4679bf5001832c6ae383b926d67a5aace3`.
The original failure was reproduced: a same-size tracked `.env` edit was
occasionally absent from Git porcelain status, allowing Source admission.
The first repair was rejected after an independent pathname replacement case
still admitted a changed secret. The revised implementation compares tracked
secret HEAD, index and current Git blob hashes inside the authorized
SourceService, rechecks the opened inode against the current path, and repeats
that verification at admission and readback completion. Secret bytes are not
placed in CAS, diff or logs. The isolated Source and Artifact tests passed 73
cases on Linux; the exact revised source target blobs were independently
reproduced. A mutation after the final admission check is a later filesystem
change and must be caught by readback. Git clean-filter differences are
rejected conservatively.

The Harness response candidate comes from `45a1f909e0c3518b19781ce9670e76c656f1788e`.
Its 18 target blobs were reproduced on the integrated base. PostgreSQL owns
the versioned binding and its attached Domain event; a trusted Node response
must carry that proof and match the selected Delivery attempt. The final
projection checks current Grant and Scope policy, WorkItem, AgentSlot, Node
binding, Runtime, accepted revision and database time. Expired or replaced
bindings are recorded as fenced late observations. Independent focused
PostgreSQL tests passed on the integrated base, with owner-only log
SHA-256 `b156e9922f76d25723911762a7fc411b0a8aeb840a9069496bef64f6b3877445`
and zero non-system test schemas afterward. The author's first full suite had
one Source secret-path failure; an independent investigation traced the
same-size Git status race. The unchanged Harness candidate passed its second
full run, and the separate Source repair addresses that race. Actual native
Harness replacement and a complete P1 Harness Gate scene remain `NOT_RUN`.

The Stale baseline probe comes from isolated candidate
`b05f39415ed2d9a3183d03edb4b64b61eeb0460a`. It reconstructs the fixed
Gate source tree as a private Git commit, creates and independently reads back
a real child commit and safe one-file diff, then changes only a private
WorkItem baseline to that child identity. Signed original execution evidence
and the ready snapshot remain on the first baseline. Real Finalizer acceptance
is rejected for corrupted CAS bytes and again for the changed baseline, with
no accepted revision or protected Effect. Full Git objects exist only in an
owner-only temporary area during the probe; persistent evidence excludes the
source copy and passed a private profile-password scan. Its isolated Domain
and Stale Gate commands passed 12 of 12 six-layer checks, with 16 other scenes
`NOT_RUN`. This is a fault-injection test of the acceptance guard, not a
production baseline-update command.

The Partial artifact probe comes from isolated candidate
`8dad5cd0a2833387aab098ed2614d7afa59c512d`. A scoped probe interrupts
the production CAS temporary file after a short write, then requires removal
and parent-directory fsync, no completed ArtifactRef, and independent readback
of a complete control artifact. The signed receipt containing the absent
output is rejected, and the WorkItem cannot reach readiness or acceptance.
Its five target blobs were reproduced; the central probe was merged by
scenario with Stale, preserving both readback paths. The exact integrated
code at `98e6fed` passed Linux focused real-resource tests with owner-only
log SHA-256 `4379b2ca4f7baf34a0a912c485d595ae07a5f4cf8dd7c555e7e6ecbf0a5e5e93`,
clean source and zero non-system PostgreSQL schemas afterward.

The integrated Runtime plus P1 probe selection passed on `d4462fc` and again
on `4110cef` before the Partial module was added; the latter owner-only log
SHA-256 is `cf8e7a635b4a64d74e195d317f43f8d9e2a1c1057e93d67eeacf86defd924696`.
The Partial addition received focused tests covering its own module and the
profile's real-resource scenario integration. Ruff and Windows no-PG tests
passed on the combined candidate. Eleven P1 scenarios now have runnable
adapters; seven do not. A new exact-head Gate run and independent live review
are required before even these eleven can be claimed on the final commit.
Actual Codex/OpenCode model turns, complete P1 acceptance and all P2 Gate
scenarios remain `NOT_RUN`.
