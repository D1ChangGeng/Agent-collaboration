# acs-continuity-recovery: model

Communication persistence and bounded technical recovery; model understanding and work outcomes are external.

- Ordinary reads do not consume messages. A resource notification is a hint to read Inbox, not evidence of model consumption.
- Retain the original message handle and client_request_id. Waiting again does not send or invoke again; identical intentional sends remain distinct.
- Timeout and caller disconnect do not withdraw the message or a later explicit reply. any/all observe original relationships.
- An ACK can be unknown after an actual dispatch. Preserve that evidence; system notices do not satisfy waits for an Agent.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-model.md); it is not the current communication contract.
