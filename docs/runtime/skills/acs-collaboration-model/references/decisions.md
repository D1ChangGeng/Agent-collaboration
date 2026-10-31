# acs-collaboration-model: decisions

Choose from the actual caller identity, current contact/receiver configuration and active tool schema.

- Use send_message for questions, replies, corrections and natural handoffs. Provide natural content and a stable recipient.
- reply_to names original messages; only the actual recipient replying to the original sender satisfies their relationship.
- The default is invoke + async. message_only stores Inbox without Native activation; sync still waits for an explicit reply.
- No WorkItem, task handoff, Review or AcceptedState is created by normal communication.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-decisions.md); it is not the current communication contract.
