# Runtime Route Scope and delegation

`create_route` creates a stable Route identity, a distinct Domain Scope, a
management AgentSlot and a scoped Grant for the authenticated creator in one
PostgreSQL transaction. The Grant is an explicit descendant of the project's
current membership Grant. Permissions and expiry are bounded by that parent;
ancestor revocation, expiry and policy changes are checked by the Domain at
actual protected boundaries. Creation requires `routes.manage` and
`grants.manage`. It provisions no Harness Session or native execution endpoint.

Root and Route revisions are separate. Concurrent replay returns one committed
Route receipt. A reused request ID with changed input is rejected. The caller's
Root revision is checked on first application. `update_route` accepts only
display name, goal, lifecycle and project-admitted SourceBinding IDs at an exact
Route revision. It also admits a bounded context manifest backed by a Source
snapshot in that exact Route Scope, after direct Management identity readback.
Scope and identity cannot move. Paused, completed and archived
Routes cannot create new WorkItems; lifecycle metadata changes do not stop
existing execution or erase recovery facts.
If lifecycle/display metadata diverges from an adopted Git registry, the Runtime
retains the old Source readback, reports `source_sync_required`, and returns a
partial context pack until an explicit Source reconciliation is verified.

Named Route, WorkItem, Message, Review and Evidence handles resolve to their
stored project-bound Scope before a tool executes. A Root Session selects its
explicit Route Grant and Slot; a Route member stays within its membership
Scope. Team configuration creates scoped delegates under that same lineage.
Root project-level metadata can enumerate its Routes. Narrow members' Route,
WorkItem, collaborator, Review, activity, connection and Source listings are
scope-filtered. Direct sibling resource reads and project-wide watches are
denied to narrow members. Source content still requires its own source/artifact
authorization; Route membership alone is not source export permission.

Runtime Route creation does not silently rewrite the Git-managed Route registry,
create source directories, replace Route knowledge or claim Source admission.
The receipt reports `management_source_state: not_materialized` until a guarded
Git management creation operation is implemented and observed. Existing Git
Routes can now be registered by the guarded installer, which verifies registry
and identity bytes before recording `adopted` with exact Source readback. A narrow
context pack returns `partial` with `route_scoped_source_hydration` missing until
its own Source and context manifest are admitted. After admission, it hydrates
actual instruction/index content and Skill metadata from that Scope's CAS. Source
admission and context hydration do not claim that the Git Route registry was
automatically materialized.

Integration tests use PostgreSQL and fixture principals. These mechanisms still
need frozen-source live management workflow evidence and independent Review.
