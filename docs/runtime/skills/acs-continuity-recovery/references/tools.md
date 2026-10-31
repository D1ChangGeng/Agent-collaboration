# acs-continuity-recovery: tools

Use the actual exposed tools; retain returned handles instead of constructing internal routing identities.

- `check_inbox`
- `list_messages`
- `read_message`
- `wait_for_response`

Communication persistence and bounded technical recovery; model understanding and work outcomes are external.

`check_inbox` also returns ACS-authored communication notifications. Use their
`notification_handle` with `read_message` to see the actual obstacle and the
notification's own Native delivery state. These notices do not satisfy a reply
wait. Definite unreachability may notify the configured direct manager; busy and
unknown Native outcomes do not authorize blind retries or automatic parent turns.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-tools.md); it is not the current communication contract.
