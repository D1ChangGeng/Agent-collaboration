# Session Relay

ACHP standardizes the message envelope, not its transport.

Possible transports include:
- user copy/paste;
- same-host session messaging;
- cross-host session messaging;
- harness-provided transports when their exact capability is verified.

## Baseline

User manual forwarding is a normal first-class transport.

Automatic relay is a progressive enhancement allowed only when:
- the exact required send scope is positively verified;
- the destination session is addressable;
- the send operation returns sufficient evidence to treat delivery as successful.

Ambiguous delivery is not success.

## Relay Envelope v1

```text
ACHP RELAY v1

Message-ID: <unique-id>
Project: <project>
Task: <task-id or none>
From: <role/session>
To: <role/session>
Intent: task | report | question | review | decision | sync
Reply-Required: yes | no

Repository-Baseline:
  Branch: <branch or n/a>
  Commit: <sha or n/a>
  Pushed: yes | no | n/a
  Receiver-Sync: none | fetch | pull-required | manual-resolution-required

Context:
<minimum context required>

Message:
<instruction/report/question>

Acceptance-or-Response:
<definition of done or requested response>

Durable-Knowledge:
<changed knowledge paths or none>
```

## Manual relay UX

When automatic delivery is unavailable or unverified:

1. state that briefly;
2. output one complete copy-ready envelope;
3. do not force the user to reconstruct technical context;
4. continue using the same message semantics as automatic relay.
