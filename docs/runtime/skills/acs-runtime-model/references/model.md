# Runtime model

Machine identifies a physical host. Node is the machine-side ACS service and
has boot/incarnation identity. Runtime is an admitted execution environment.
Harness is the external Agent product. Driver maps ACS lifecycle operations to
the native API. Session is a replaceable Harness context. Endpoint is a logical
delivery target. Attempt is one WorkItem execution try.

The Node owns local observations and journal. The Domain Authority owns
authorization and accepted state. Drivers report native facts and do not own
Policy.

Capabilities include operation, direction, scope, component versions,
credential scope, observed_at, expires_at and evidence. Unknown or expired
capability is unavailable for admission.
