# Durable Knowledge Policy

Project-level durable knowledge lives under:

```text
.agents/knowledge/
```

## Capture test

Persist a finding only when:

1. a plausible future task will need it;
2. rediscovery is materially more expensive than preserving it;
3. source/config/tests are not already a better source of truth;
4. it changes a future decision, implementation, verification step, or risk judgment;
5. its scope can be stated clearly;
6. important claims can be traced to evidence.

## Categories

- `guides/` — scoped maps, policies, runbooks, constraints.
- `decisions/` — consequential adopted choices, rationale, alternatives, consequences, reconsideration conditions.
- `observations/` — high-value provisional findings not yet ready for an authoritative home.
- `archive/` — superseded material kept only when historical value is real.

## Maintenance

Prefer:
- one authoritative current location;
- routes/links instead of duplicate summaries;
- correction over accumulation;
- evidence and uncertainty;
- smallest relevant context.

Never persist credentials, secrets, transient debug dumps, or machine-local session capabilities here.
