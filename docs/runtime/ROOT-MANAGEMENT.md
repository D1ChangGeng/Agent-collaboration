# Root management and first-entry identity

This change follows S00's distinction between communication organization,
management context and execution capacity, as retained by development package
v2.33 SPEC 01/03/06 and the user's 2026-11-02 clarification. It changes the actual
MCP entry, authorization, context and persistence paths.

## Project and Root

S00 gives Project a grouping/isolation purpose and Management Root a configuration
and context-source purpose. It does not require two independently operated
management lifecycles. Current storage already pairs a Project namespace with one
Root and one root Scope, uniquely within its tenant.

Keep these existing stable keys and authorization relationships. Expose
`configure_root` as the normal Owner management operation. It establishes the
communication namespace when absent, connects existing management files when
provided, changes specified Root settings, and optionally configures its Root
manager in the same transaction. There is no additional Project manager or
separate Agent-facing Project admission step. Selecting existing files does not
copy them or initialize another repository/workspace. Existing installer adoption
continues to work through its original registration path.

`project_id` remains the routing/isolation key. `root_id` is stable and defaults
to that key on first setup. A display rename changes `name`. Request identity,
concurrent first setup, stable Root uniqueness and optional old-value/revision
conditions are checked in PostgreSQL. Invalid manager configuration rolls back
the whole first setup. Current-file `configure_project` calls remain compatible
for existing callers, while normal discovery exposes the single Root entry.

## Actual role sequence

| Identity | First entry and continued context | Management boundary |
|---|---|---|
| Trusted Client | `read_profile.actor` explicitly identifies Client, no synthetic Slot or fixed Native Session; select an existing namespace or configure a Root | Establish Roots and configure their managers within the admitted Owner trust domain |
| Root Agent / Root manager | Actual stable address, Root binding, configured upper contact, Inbox/history/contact actions and current Root documents | Configure its Root, create Routes and configure Route managers; cannot create peer Roots or rewrite another Root manager |
| Route manager | Actual Route Scope, upper contact and current communication actions | Configure ordinary collaborators within its own Scope; Route creation is absent from discovery and rejected on calls |
| Ordinary Agent | Own address, actual manager, current Inbox/history/contact actions | Communicate and use existing authorized capabilities; no new management tier |

Profile names remain compatibility/eligibility metadata. They are not sufficient
to infer Client status, and loading context does not switch an identity. Identity
comes from the trusted stdio/OAuth binding and current authoritative records.
Role changes, revoked Grants, inactive Slots and inactive Scopes invalidate old
management access. A trusted binding must be refreshed after changing roles.

Context actions are checked through the same authorization path as calls. OAuth
scopes additionally narrow discovery, context actions and execution even on an
Owner deployment. Invalid input receives bounded field guidance only where the
caller may discover the operation; unavailable authorization is not portrayed
as a successful read.

## Communication and Session boundaries

Root and team configuration report committed settings separately from actual
receiving preparation. Only the real Adapter can supply a Native Session ID.
The Client's lack of a fixed Session does not prevent ordinary communication.
`list_harnesses` remains a read-only observation. These changes add no task,
Harness execution controller, Native result collector or business acceptance
state.

A reply addresses the original peer and retains that peer's request in
`reply_to`. Delegating to a third Agent starts a new message, with relevant
background in its content. A readable but mismatched reply relationship still
rejects with `authorization_denied` and safe corrective guidance; an unreadable
private reference reveals neither its existence nor its participants.

Team versions are independent of Root and Route versions. Partial updates may
omit `expected_revision` and protect observed fields with `if_unchanged`.
Conflicts explain the relevant field; no automatic replacement of the caller's
old-value condition is introduced.

Verification and deployment status belong to the accompanying evidence, not
this architectural explanation. Scripted MCP peers, independent model Sessions
and production cutover remain separate claims.
