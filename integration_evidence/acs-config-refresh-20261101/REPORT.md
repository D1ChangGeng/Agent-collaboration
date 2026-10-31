# Trusted receiver-setting refresh

The v2.0.3 slice addresses R08/R15/R22/R24/R26/R32 using source based on
`107ebe540fdd27990775e1d1868ef43379be7ef5`.

`ConfiguredRemoteEndpoint` already reloaded registered endpoint revisions, but
its local receiving settings were captured once. A long-lived entry could
therefore combine a current registration with an older journal generation.
The receiver's generation fence correctly rejects such a prepare before any
Native effect. Refreshing only a newly opened client does not retire older
maintenance entries sharing the same durable queue.

The configured service now supplies a trusted file-backed settings provider.
Before constructing or reusing the adapter, it reads the current receiving
settings for that exact endpoint and invalidates the cache on changes. It
requires the original subject/context, access mode, DSN reference and resolved
DSN, and credential reference. A changed identity/storage configuration or
removed endpoint requires reconnection. This is endpoint refresh, not a
general identity or authorization hot-rebinding mechanism.

Status reads remain observation-only. Missing or unauthorized configuration
cannot cause a prepare command or model invocation. Receiver signature,
lineage, generation and Native anti-replay checks are retained. The constructor
without a provider preserves explicitly supplied deployment behavior.

Component/private-file regressions verify a generation change even with the
same registered revision, adapter reuse/invalidation, adopted isolation
reference, subject/access-mode/DSN-value/DSN-reference/credential/removal
refusal, and no prepare side effect from status. Windows ran 14 passing cases.
Actual Linux ran those cases plus the current PG/TLS/SQLite signed-receiver
regressions: 17 passed. Native acknowledgements in that database suite are
explicit controlled callbacks, not model replies.

An initially selected historical Owner test expected `create_work` and failed
against the current retired-task surface. It was not restored or counted as a
current communication acceptance test. Current signed-receiver tests require
POSIX private paths and were rerun on Linux rather than treating Windows skips
as passes.

Upgrade from code predating this loader requires reconnection of old ACS
maintenance entries once; a running old Python implementation cannot acquire
new behavior from a changed disk version alone. The intended actual warm-client
check retains one current MCP connection across an endpoint-generation update,
then submits through ordinary tools and checks the real reply. Deployment and
that check are reported separately; this component report does not itself
claim they ran.

No physical-host reboot, new task domain, terminal-result projection,
credential export or automatic Git synchronization is introduced. Aggregate
test evidence contains no production handles, account details or raw model
output.
