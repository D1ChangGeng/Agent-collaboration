# Collaboration tool map

- list_collaborators reads Slots, principals, duties, assignments and observed
  Session activity.
- configure_team revisions owner business members and Harness requirements;
  shared mode additionally manages its Grant, Policy and budget bindings.
- create_work and revise_work record WorkItem intent and expected revisions.
- handoff_work records responsibility transfer and lineage.
- send_message commits Message, response expectation and notification state.
- read_message reads or consumes Message and response content.
- request_review creates an exact candidate and reviewer relationship.

The caller supplies project_id, stable client_request_id and the applicable
expected revisions. Ordinary owner members use slot, principal, role and
Harness requirements. The active service schema defines optional metadata and
shared-mode inputs.

send_message defaults to async and returns committed handles. Sync waits for
the target condition; an optional caller timeout returns pending handles for
later observation. Owner Message deadline is optional. Reusing a submission
identity retains the same Message across wait preferences and transport
recovery.
