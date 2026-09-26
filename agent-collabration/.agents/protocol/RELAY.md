# Root / Route Relay

ACHP standardizes message semantics, not a vendor API. Manual user forwarding
is a first-class transport. Automatic relay requires a positively verified,
topology-appropriate send capability and an addressable destination.

## Root-aware envelope

```text
ACHP RELAY v2

Root-ID: <root-id>
Route-ID: <route-id or none>
Endpoint-ID: <endpoint-id or none>
From: <role/session>
To: <role/session>
Intent: task | report | question | review | decision | sync | baseline
Reply-Required: yes | no

Source-State-Ref: <route source-state path or unknown>
Source-State-Evidence: direct | reported | external | baseline | unknown
Repository-Sync: none | fetch | pull-required | manual-resolution-required | unknown

Context:
<minimum context required>

Message:
<instruction/report/question>

Acceptance-or-Response:
<definition of done or requested response>

Durable-Knowledge:
<changed knowledge paths or none>
```

Sibling Route synchronization is minimal-necessary: relay only facts,
decisions, dependencies, risks, or source-state changes that can alter the
receiver's next action. Route-to-Route logical permission does not prove a
current Harness send capability; unknown capability falls back to one complete,
copy-ready manual envelope.
