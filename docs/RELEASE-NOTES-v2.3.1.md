# ACS v2.3.1

Fresh Client directories identify the caller by its resolved communication
address. A legacy Root Slot sharing the Client's Principal is not marked as
that Client; separate Slots sharing a Principal retain their own self identity.
Old descriptive organization labels no longer replace the configured role.

Owner Route-scoped callers cannot select sibling Route context or change sibling
Route settings. Client and Root managers retain authorized project-wide access.
Current context, tool discovery and actual refusal checks follow the same live
binding and Scope. Project remains the Root's communication namespace.

A receiving host can explicitly bind saved owner-local management locations to
an admitted SSH file connection. It reads the owner's current files and reports
their actual paths and content hashes while native local file tools retain the
receiving machine. The optional forced-command peer admits only context and file
reads within configured roots, using the existing collaborator identity and
live authorization checks before and after the read. Its machine advertises its
allowed operations and rejects writes locally and remotely.

Read-only context authorization no longer takes a Project write lock. A remote
file peer can reauthorize the same Project while the outer context read is in
progress. Mutating operations retain their locking and revision checks.

The existing startup lifecycle can independently recover the admitted file peer
and its loopback SSH tunnel. It verifies binary/configuration hashes and owned
process identity. The recovery worker refreshes itself when the active Release
changes. Current role and Skill guidance uses Client, Root, Route manager and
ordinary collaborators; earlier task terminology is an explicit historical
reference.

The Core/Project Schema remains 2 and the MCP tool catalog remains 12. Upgrading
from v2.3.0 needs no database migration. Preserve the existing host/account,
Runtime-only selection, Harnesses, web settings, credentials and journals. The
read-only cross-host file connection is an explicit operator configuration, not
an automatically chosen different checkout. Existing MCP processes keep the
version they started; fresh connections load the activated version.

Qualification and production verification are separate evidence scopes. Native
completion is not an Agent reply; the same ordinary `send_message` and exact
reply relationship continue to govern communication acceptance.
