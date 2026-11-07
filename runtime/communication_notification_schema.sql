-- Optional MCP hint publication progress. This is not read/consumption state.
-- The base session table remains independently versioned for legacy clients.
CREATE TABLE IF NOT EXISTS communication_notification_frontiers (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    session_ref TEXT NOT NULL,
    binding_revision BIGINT NOT NULL CHECK(binding_revision > 0),
    message_sequence BIGINT NOT NULL DEFAULT 0 CHECK(message_sequence >= 0),
    notice_sequence BIGINT NOT NULL DEFAULT 0 CHECK(notice_sequence >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,owner_ref,session_ref,binding_revision),
    FOREIGN KEY(tenant_id,project_id,owner_ref,session_ref)
        REFERENCES collaboration_notification_sessions(tenant_id,project_id,owner_ref,session_ref)
);
