# Collaboration tool map

- list_collaborators reads Slots, roles, assignments and Session activity.
- configure_team revisions members, Policies, Grants and budgets.
- create_work and revise_work own WorkItem intent.
- handoff_work owns responsibility transfer.
- send_message owns Message, response expectation and notification creation.
- read_message consumes Message or response content.
- request_review creates a specialized Review relationship.

The caller supplies project_id and exact revisions. Result handles and
follow-ups are the continuity contract for later Sessions.
