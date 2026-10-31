-- Current project identity, contacts, SourceBindings and notification sessions.
CREATE TABLE IF NOT EXISTS collaboration_projects (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
    name TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','archived')),
    context_manifest JSONB NOT NULL,
    adopted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id),
    UNIQUE(tenant_id,root_id),
    UNIQUE(tenant_id,scope_id)
);

CREATE TABLE IF NOT EXISTS collaboration_memberships (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    grant_ref TEXT NOT NULL REFERENCES grants(grant_ref),
    profile TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL REFERENCES agent_slots(agent_slot_id),
    PRIMARY KEY(tenant_id,project_id,principal_ref,profile),
    FOREIGN KEY(tenant_id,project_id)
      REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE TABLE IF NOT EXISTS collaboration_routes (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    state TEXT NOT NULL DEFAULT 'active',
    definition JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,route_id),
    FOREIGN KEY(tenant_id,project_id)
      REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE TABLE IF NOT EXISTS collaboration_route_grants (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    profile TEXT NOT NULL,
    grant_ref TEXT NOT NULL UNIQUE REFERENCES grants(grant_ref),
    agent_slot_id TEXT NOT NULL UNIQUE REFERENCES agent_slots(agent_slot_id),
    PRIMARY KEY(tenant_id,project_id,route_id,principal_ref,profile),
    FOREIGN KEY(tenant_id,project_id,route_id)
      REFERENCES collaboration_routes(tenant_id,project_id,route_id)
);

CREATE TABLE IF NOT EXISTS collaboration_commands (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
    command_id TEXT NOT NULL,
    result_json JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,principal_ref,client_request_id),
    UNIQUE(tenant_id,command_id),
    FOREIGN KEY(tenant_id,project_id)
      REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE TABLE IF NOT EXISTS collaboration_sources (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision > 0),
    current_commit TEXT NOT NULL,
    repository_identity JSONB NOT NULL,
    PRIMARY KEY(tenant_id,project_id,source_id),
    FOREIGN KEY(tenant_id,project_id)
      REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE TABLE IF NOT EXISTS collaboration_source_snapshots (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL CHECK(length(snapshot_digest)=64),
    snapshot_json JSONB NOT NULL,
    command_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,source_id,source_commit),
    FOREIGN KEY(tenant_id,project_id,source_id)
      REFERENCES collaboration_sources(tenant_id,project_id,source_id)
);

CREATE TABLE IF NOT EXISTS collaboration_teams (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,scope_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision>0),definition JSONB NOT NULL,
    PRIMARY KEY(tenant_id,project_id,scope_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE TABLE IF NOT EXISTS collaboration_team_members (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL REFERENCES agent_slots(agent_slot_id),
    principal_ref TEXT NOT NULL,role TEXT NOT NULL,profile TEXT NOT NULL,
    grant_ref TEXT NOT NULL REFERENCES grants(grant_ref),budget_ref TEXT NOT NULL,
    harness_requirements JSONB NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','retired')),
    PRIMARY KEY(tenant_id,project_id,agent_slot_id),
    FOREIGN KEY(tenant_id,project_id,scope_id) REFERENCES collaboration_teams(tenant_id,project_id,scope_id)
);

CREATE TABLE IF NOT EXISTS collaboration_notification_sessions (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,owner_ref TEXT NOT NULL,
    session_ref TEXT NOT NULL,connection_ref TEXT NOT NULL,revision BIGINT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','retired')),
    PRIMARY KEY(tenant_id,project_id,owner_ref,session_ref),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS collaboration_one_notification_session
    ON collaboration_notification_sessions(tenant_id,project_id,owner_ref) WHERE state='active';

ALTER TABLE collaboration_notification_sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
