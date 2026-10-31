# acs-web-collaboration: decisions

Choose from the actual caller identity, current contact/receiver configuration and active tool schema.

- Use the actual authenticated subject/Slot binding and current tool schema. A read capability does not prove send or Native initiation support.
- After reconnecting, read durable Inbox/history and retain the original references. Notifications are not replies.
- OAuth consent, ingress, Native readiness and configuration adoption are separate; report missing capabilities honestly.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-decisions.md); it is not the current communication contract.
