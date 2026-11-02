# Agent identity, management and responsibilities

ACS is communication software used and managed by autonomous Agents. Current
behavior follows [Root management](ROOT-MANAGEMENT.md) and
[the communication contract](COMMUNICATION.md).

| Actual identity | Context and management |
| --- | --- |
| Trusted Client | Manages admitted Root namespaces and their managers; needs no synthetic Slot or fixed Native Session |
| Root Agent / Root manager | Manages its existing Root, creates Routes and configures Route managers |
| Route manager | Manages ordinary collaborators and Route settings within its own Scope |
| Ordinary Agent | Uses its stable address, contacts, Inbox and history; communicates with authorized peers |

Project is the Root's communication namespace and isolation key. `configure_root`
establishes or configures that Root and can configure its manager in the same
operation. Loading another Project or Route changes context rather than identity.

`read_profile.actor` and `load_project.actor_binding` describe the trusted current
binding. Display names and Profile names do not create identity. Multiple Slots
sharing one Principal remain separate communication identities. `is_self` compares
the resolved communication address, including Client-origin addresses.

Engineer, reviewer, specialist and finalizer describe responsibilities performed
in the Agent's own Harness. Reasoning, planning, code synchronization, work review
and acceptance remain Agent activities. ACS provides natural messages, explicit
reply relationships, durable history and necessary receiving initiation.

Tool discovery and calls check current identity and scope. Shared Grants and
OAuth scopes can additionally narrow operations. A Route-scoped caller cannot
select another Route to obtain its context or change its settings. Role changes
and revocation invalidate stale bindings. Legacy descriptive organization labels
do not replace the currently configured role.

Management documents report their actual machine, path, observation and hashes.
When another host reads the owner's files, its trusted file connection names that
origin explicitly. Native local files retain their own machine namespace.

Earlier terminology and task proposals are retained in
[the v6 historical record](LEGACY-V6-AGENT-ORGANIZATION-MODEL.md).
