# ACS v2.3.0

First-entry `read_profile.actor` now identifies the trusted Client, Root,
Route manager or ordinary collaborator and reports current bindings and
authorized continuation actions. Client management needs no fixed Native
Session or synthetic Slot. Current context uses Inbox, history and contact
actions, with live checks shared by tool discovery and calls.

`configure_root` establishes or configures one Root and its communication
namespace, attaches existing current management files, and optionally configures
its manager atomically. Project remains the isolation/routing key. Existing IDs,
history and files are preserved. The former current-file `configure_project`
operation remains a hidden compatibility entry.

Context and project discovery now reuse the existing contact authority. Multiple
Slots sharing a Principal retain their correct identity; a shared Grant requires
the trusted Slot when ambiguous. Management checks the caller's resolved address
and the target's current role, protecting existing peer managers against a
demotion-field bypass. Replaced legacy Owner bindings reject. Shared and OAuth
permissions narrow context actions and tools as well as execution.

The published tool catalog is revision 12. Actor/result metadata, nested Root
configuration validation, independent team revisions and safe reply-association
guidance match the implementation. The [qualification report](../integration_evidence/acs-identity-root-20261102/REPORT.md)
records four independent model Sessions, three original-Session continuations,
exactly six messages and three associated replies, cross-platform integration,
installed-package verification and the explicit environment limits.

Upgrading from v2.2.0 requires no database migration. The tool catalog changed,
so the automatic updater deliberately reports `review_required`. Perform the
explicit upgrade with this Release's verified `acs_bootstrap.py --version
v2.3.0` on the existing confirmed host/account, preserving its Runtime-only,
Harness and web selections. Retain the previous version for rollback. Receiver
upgrades use the existing independently verified wheel, signed registration and
generation/isolation procedure with the original identities, credentials and
journals. Refresh cached web connector tool definitions when needed to expose
`configure_root`.

The four-model role qualification uses `message_only`. Physical Native and
public browser/TLS qualification remain separately reported; software release
and production readback do not replace those communication checks.
