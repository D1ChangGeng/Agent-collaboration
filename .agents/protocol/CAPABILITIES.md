# Capability Model

Capabilities are runtime facts, not Harness-brand assumptions.

## Topology-first probing

```text
one session
  -> no relay capability needed

multi-session, same host
  -> evaluate same-host destination addressing and send capability

multi-session, multiple hosts
  -> evaluate cross-host destination addressing and send capability

unknown topology
  -> do not block; use user manual relay unless the needed send capability is otherwise concretely verified
```

Do not test cross-host relay merely because the project supports multi-agent work.

## Independent capability dimensions

A runtime may independently expose:

```text
session.discover.same_host
session.read.same_host
session.send.same_host

session.discover.cross_host
session.read.cross_host
session.send.cross_host

repository.read
repository.write
repository.fetch
repository.pull
repository.push
```

Represent observations as:

```text
verified
unavailable
unknown
```

`unknown` must not be upgraded to `verified`.

Read is not send.
Discovery is not send.
Same-host is not cross-host.

## Observation boundary

Capability observations belong to the current Harness/session context. The
setup scaffold does not require a persisted record, and a local observation
must not be promoted to universal project truth without separately verified
evidence.

## Selection

```text
if no other session is involved:
    transport = none
else:
    required_scope = same_host or cross_host
    if target_is_addressable and send[required_scope] == verified:
        transport = automatic
    else:
        transport = user_manual
```

Capability can differ by message direction.
