# P1 Harness binding, Machine identity and Lease probe review

Decision: `PASS_BOUNDED` for integrating the three reviewed components from
formal work-branch base `d9d7d957421fd184ca3f9ef53d6ecb5bb8cea170`.
The integrated candidate is `a64e5a97935fdffae495477fdfdcdea082fc22db`
with tree `8b86710a60d2a4ac9be84e0ee9b48c31e802c313`. This is a component
and eight-scenario probe result, not P1 acceptance.

The combination adds the Runtime 1.10 PostgreSQL HarnessSessionBinding command
and readback, binds Node/PG/Gate Machine identity to one observed host, and
exercises real Lease replacement and late-writer fencing through a local file
effect. It also aligns the probe profile with the accepted host-only OS
observation and registers shared delivery test fixtures before full suite
collection. The integrated branch descends directly from the formal base; the
reviewed source target blobs match their frozen candidates, except for the
intentional probe-document correction and test fixture registration.

On the isolated Linux clone at exact candidate commit, the full
`runtime_tests` suite passed with exit code 0 and Ruff passed. The lockfile
check passed with `uv lock --check --no-config`; the host's default uv config
redirects package resolution to another index, so that default-mode diff is
not a source lockfile change. Windows focused checks and Ruff passed. The
candidate checkout remained tracked-clean.

An owner-only real-resource Gate run at exact candidate commit and tree passed
eight of 18 P1 scenarios: Domain transaction, auth revocation, command dedup,
Inbox ACK loss, Core restart, Node restart, Provider restart, and Lease
fencing. All 48 six-kind commands passed; the other ten scenarios stayed
`NOT_RUN`, and the run's overall result stayed `blocked`. Its run ID is
`p1-run-29ffa5073427ce75f3431d020c488ef3`; state SHA-256 is
`c117ef516014dbb4e863972044990cb5456e8c63315071755da0761f86e455ff`,
and run-manifest SHA-256 is
`eaeca17497d88c854eca2b623cce2e6ea5a8e0fef05b1262f2ba7c0306c1c938`.
No formal Gate file was changed.

The independent reviewer verified the HMAC and 112 run-manifest file hashes,
modes and symlink exclusions; all 48 command outputs; eight host OS attestations;
eight Node SQLite journals; the live PostgreSQL schema/authority rows; both
Lease generations; eight completed Temporal workflows; and the current local
effect SHA, inode and 11 owner-only markers. The reviewer separately confirmed
that generation 2's new file was read back before the old owner's late write was
rejected. The owner-only independent review JSON SHA-256 is
`824a181a737649d5f8a719c3d6ed0d84bf96a9338d9f2d855d153c9b436b49a5`.
After review, a bound cleanup dropped only the eight run-owned `p1_probe_*`
PostgreSQL schemas, confirmed zero residual probe schemas, and preserved the
state and manifest hashes. Its owner-only report SHA-256 is
`899b9dea6b12f3428db997aad0e4d3add2340bf857a31ac8bf01526ba0d18556`.

The Harness binding API records supplied native session and receipt references;
native Harness replacement and the `delivery.project_native_response` proof
consumer are still `NOT_RUN`. The eight-scenario run belongs to the isolated
candidate commit. Any later source commit needs its own exact-baseline Gate
run before Gate status can be promoted. The remaining P1 scenes, real model
lifecycle, complete P1 acceptance and P2 collaboration are pending.
