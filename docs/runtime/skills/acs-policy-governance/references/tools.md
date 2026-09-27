# Governance tool map

- read_profile exposes authenticated identity, Profiles and OAuth scope summary.
- list_projects returns only authorized Projects.
- list_connections returns metadata without credentials.
- configure_team changes AgentSlot, Role, Grant, Policy and budget bindings under
  its management permissions.
- accept_work requires acceptance permission and applicable decision input.
- submit_command is an Operator Profile surface for complete Domain commands.

Every project tool validates project_id and handle ownership. Result metadata
retains subject lineage, evidence class and observation time.
