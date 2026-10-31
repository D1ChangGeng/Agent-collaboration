# Governance tool map

- read_profile exposes trusted identity, tenant, access_mode, client Profiles
  and connection state.
- list_projects returns active Projects visible to that context.
- list_connections returns registration and connection metadata with secret
  references kept in their credential authority.
- configure_team stores owner slot, principal, role and Harness requirements;
  shared deployments also manage Grant, Policy and budget bindings.
- accept_work checks candidate, Review and acceptance prerequisites.
- submit_command exposes complete Domain commands for the admitted advanced
  client surface.

Every Project tool validates project_id, typed handle ownership and current
object state. Mutations add stable client_request_id, canonical input
deduplication and expected revisions. Owner business deadline is optional.
The active tool catalog defines exact required and optional fields.

Result metadata retains subject lineage, evidence class, source revision and
observation time. Profiles describe the visible client view; shared
authorization applies its server-side Grants and Policy. Explicit revocation
and actual transport, resource and acceptance checks remain effective in both
modes.
