# Runtime decision map

Select capacity only from current capability evidence matching project, Scope,
role, operation, direction and deadline.

Replace a Session while preserving Project, Route, AgentSlot, WorkItem and
Message identity. Replace an Attempt when execution identity changes. Fence the
old Attempt before protected resource use.

A Lease renewal proves current ownership only at the protected boundary.
Unfenceable resources remain unavailable until the old owner is isolated or
confirmed stopped.

For uncertain effects, read the external authority marker and result before
adopting, compensating or authorizing another Attempt.
