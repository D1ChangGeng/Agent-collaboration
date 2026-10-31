# ACS v2.0.0

ACS connects independent Agents through stable contacts, natural messages,
explicit associated replies and a durable Inbox. The default MCP entries
maintain pending delivery and request one authorized Native input when needed.

## Changed behavior

- `send_message` uses `to`, natural `content` and optional `reply_to`. Default
  activation is invoke and default response mode is async.
- Sync and `wait_for_response` observe the recipient's first explicit reply.
  Native completion and system notifications never substitute for that reply.
- Inbox/history reads preserve messages; long UTF-8 content has bounded
  continuation actions. Timeouts and reconnects do not withdraw communication.
- Caller identity comes from trusted bindings. Configuration merges explicit
  fields, preserves other members and reports actual receiver/Session observations.
- Project context reads current authorized machine files. Recorded Source
  archives require an explicit source and revision. Owner project configuration
  is unavailable to ordinary Agents and Shared profiles.
- WorkItem, task Handoff, Review/AcceptedState and execution-result projection
  are retired from the normal Runtime. Agents exchange work and review findings
  as messages. Historical records remain read-only under their real provenance.
- Fresh storage creates 46 tables. Existing legacy tables and authoritative
  retry, receipt, signature and Native admission records are retained on adoption.

## Upgrade from v1.x

This is a major contract change. Automatic updates do not activate it. Use the
setup Skill for the selected existing Runtime host and clients, retaining its
machine/account binding, credentials, project identity and Node keys.

1. Inventory the actual metadata, pending communication, receivers and clients.
   Take a consistent PostgreSQL snapshot and private configuration backup.
2. Restore the snapshot in isolation. The adoption tool accepts only known
   exact 1.13/1.14 schema fingerprints or an existing communication core. Unknown
   schemas, missing ledgers or missing Native fences are rejected.
3. Quiesce the selected old service/receivers before adopting production storage.
   Preview `scripts/acs_communication_adopt.py` with the private DSN referenced
   through `--dsn-env` and the actual `--schema`. Apply only with its unchanged
   `--expected-plan-sha256`. This creates communication indexes and metadata;
   it does not clean data, create identities or start Native execution.
4. Inventory/adopt historical message associations with
   `scripts/acs_communication_inventory.py` when needed. Unknown associations
   remain unknown; old Native output is not converted into an Agent reply.
5. Activate the verified distribution and update registered receivers to their
   matching signed factory configuration. Preserve Node identity and keys;
   use the next actual endpoint revision and retain dispatch/Journal fences.
6. Reconnect clients. Verify actual tools, profile and project context, then an
   authorized independent A/B exchange. Old task tools are intentionally absent.

Rollback requires the backed-up code/configuration, database and pending-effect
boundary to agree. Do not blindly restore an earlier database over newly
accepted messages, or replay a possibly dispatched Native operation. Rehearse
the selected rollback while services are quiescent before activation.

## Verification scope

The [support record](runtime/COMMUNICATION-STATUS.md) separates scripted
mechanism tests, actual protocols and independent models. It includes physical
Windows Codex→Linux OpenCode and an actual installed Linux Receiver console
with independent Codex/OpenCode contexts. The v2 integration also retains
v1.6 current-file management and installation/startup recovery improvements.

Shared OpenCode/restricted Systemd Native, opposite physical Native directions
and larger sustained load require their own qualification. A prior Windows
localhost→WSL test-database path encountered connection failures; that experiment
does not qualify that path. Model/runtime costs are not a transport SLA.
