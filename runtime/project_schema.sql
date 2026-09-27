-- Project management extends the existing PostgreSQL Domain. WorkItem,
-- delivery, receipt, Review and accepted-state records remain in their
-- original tables; these tables hold identity and continuation links only.
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
CREATE TABLE IF NOT EXISTS collaboration_work_links (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL REFERENCES work_items(work_item_id),
    route_id TEXT NOT NULL,
    definition JSONB NOT NULL,
    PRIMARY KEY(tenant_id,project_id,work_item_id),
    UNIQUE(tenant_id,work_item_id),
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
CREATE TABLE IF NOT EXISTS collaboration_response_tracking (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    initiating_principal TEXT NOT NULL,
    initiating_slot TEXT NOT NULL REFERENCES agent_slots(agent_slot_id),
    response_handle TEXT NOT NULL,
    delivery_policy TEXT NOT NULL CHECK(delivery_policy IN ('queue_until_idle','steer_active_turn')),
    expect_response BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,message_id),
    UNIQUE(tenant_id,response_handle),
    FOREIGN KEY(tenant_id,project_id)
      REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(tenant_id,message_id)
      REFERENCES delivery_messages(tenant_id,message_id)
);
CREATE TABLE IF NOT EXISTS collaboration_response_subscriptions (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    revision BIGINT NOT NULL DEFAULT 1 CHECK(revision > 0),
    consumed_at TIMESTAMPTZ,
    PRIMARY KEY(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id,message_id)
      REFERENCES collaboration_response_tracking(tenant_id,project_id,message_id)
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
CREATE TABLE IF NOT EXISTS collaboration_team_budgets (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,scope_id TEXT NOT NULL,
    budget_ref TEXT NOT NULL,revision BIGINT NOT NULL,max_messages INTEGER NOT NULL CHECK(max_messages>0),
    max_pending_messages INTEGER NOT NULL CHECK(max_pending_messages>0),
    expires_at TIMESTAMPTZ NOT NULL,messages_used INTEGER NOT NULL DEFAULT 0 CHECK(messages_used>=0),
    PRIMARY KEY(tenant_id,project_id,budget_ref),
    FOREIGN KEY(tenant_id,project_id,scope_id) REFERENCES collaboration_teams(tenant_id,project_id,scope_id)
);
CREATE TABLE IF NOT EXISTS collaboration_budget_reservations (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,budget_ref TEXT NOT NULL,
    message_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,message_id),
    FOREIGN KEY(tenant_id,project_id,budget_ref)
      REFERENCES collaboration_team_budgets(tenant_id,project_id,budget_ref),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
      DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS collaboration_review_requests (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,request_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,work_revision BIGINT NOT NULL,revision BIGINT NOT NULL,
    candidate_ref TEXT NOT NULL,source_baseline TEXT NOT NULL,
    reviewer_ref TEXT NOT NULL,reviewer_grant_ref TEXT NOT NULL,
    assignment_revision BIGINT NOT NULL,state TEXT NOT NULL,
    definition JSONB NOT NULL,evidence_refs JSONB NOT NULL,submission JSONB,
    review_id TEXT REFERENCES reviews(review_id),
    PRIMARY KEY(tenant_id,project_id,request_id),
    FOREIGN KEY(tenant_id,project_id,work_item_id)
      REFERENCES collaboration_work_links(tenant_id,project_id,work_item_id)
);
CREATE TABLE IF NOT EXISTS collaboration_inbox_consumptions (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,owner_ref TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('message','review')),item_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision>0),consumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,owner_ref,kind,item_id,revision),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS collaboration_watches (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,watch_id TEXT NOT NULL,owner_ref TEXT NOT NULL,
    targets_digest TEXT NOT NULL,targets JSONB NOT NULL,event_kinds JSONB NOT NULL,
    delivery_policy TEXT NOT NULL,revision BIGINT NOT NULL,enabled BOOLEAN NOT NULL DEFAULT TRUE,
    start_snapshot pg_snapshot NOT NULL,
    PRIMARY KEY(tenant_id,project_id,watch_id),
    UNIQUE(tenant_id,project_id,owner_ref,targets_digest),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS collaboration_inbox_notifications (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,notification_id TEXT NOT NULL,
    owner_ref TEXT NOT NULL,watch_id TEXT NOT NULL,event_id BIGINT NOT NULL REFERENCES domain_events(event_id),
    payload JSONB NOT NULL,consumed_at TIMESTAMPTZ,
    PRIMARY KEY(tenant_id,project_id,notification_id),
    UNIQUE(tenant_id,project_id,watch_id,event_id),
    FOREIGN KEY(tenant_id,project_id,watch_id) REFERENCES collaboration_watches(tenant_id,project_id,watch_id)
);
CREATE TABLE IF NOT EXISTS collaboration_watch_observations (
    tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,watch_id TEXT NOT NULL,event_id BIGINT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,watch_id,event_id),
    FOREIGN KEY(tenant_id,project_id,watch_id) REFERENCES collaboration_watches(tenant_id,project_id,watch_id),
    FOREIGN KEY(event_id) REFERENCES domain_events(event_id)
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
