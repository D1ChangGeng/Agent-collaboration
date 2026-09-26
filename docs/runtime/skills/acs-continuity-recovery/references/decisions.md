# Continuity decision map

A wait timeout changes observation only; response tracking and notification
continue. A Session disconnect preserves Message, response and Inbox state.

ACK loss triggers readback and retry with the same Message identity. Duplicate
delivery converges on the prior receipt. Session replacement targets the current
binding while retaining logical recipient identity.

Human Bridge is an incident recovery provider after eligible automatic paths
are exhausted. Manual return is authenticated, deduplicated and subject to the
same deadline, revision and Policy.

Recovery classifies pending delivery, replacement, stale owner, source drift,
uncertain effect and expired authority before choosing an action.
