# Project Knowledge

This directory is the durable project-level knowledge plane shared across Agents and sessions.

The policy is intentionally lightweight:

- preserve only knowledge that changes a future action;
- retrieve the smallest relevant context;
- keep evidence and uncertainty visible;
- correct stale authoritative knowledge instead of accumulating contradictions;
- prefer current source/config/tests/runtime facts when they are the better authority.

## Structure

```text
guides/
decisions/
observations/
archive/
```

This model can be maintained manually or by a compatible knowledge/self-evolution Skill. ACHP itself does not require a specific knowledge tool.
