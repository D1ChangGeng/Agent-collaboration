# acs-runtime-model: decisions

Choose from the actual caller identity, current contact/receiver configuration and active tool schema.

- list_harnesses is observation only: it does not prepare, spawn, resume or invoke.
- Configuration commit, receiver preparation and observed Native Session are distinct facts; only a real Adapter supplies a Session ID.
- Busy, offline and unknown are different. Use supported queueing; an uncertain dispatch is not permission to invoke again.
- Native final output is not a reply. ACS does not continuously observe execution or decide work completion.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-decisions.md); it is not the current communication contract.
