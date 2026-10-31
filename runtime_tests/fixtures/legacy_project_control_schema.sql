-- Explicit P2 control-plane adoption. Existing project and Domain rows are preserved.
ALTER TABLE collaboration_notification_sessions
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS collaboration_handoffs (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    handoff_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    assigned_work_revision BIGINT NOT NULL CHECK (assigned_work_revision > 0),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    from_agent_slot TEXT NOT NULL,
    to_agent_slot TEXT NOT NULL,
    to_principal_ref TEXT NOT NULL,
    to_grant_ref TEXT NOT NULL,
    initiated_by TEXT NOT NULL,
    source_state JSONB NOT NULL,
    source_digest TEXT NOT NULL CHECK (length(source_digest) = 64),
    context_handles JSONB NOT NULL,
    evidence_handles JSONB NOT NULL,
    unresolved_items JSONB NOT NULL,
    message_id TEXT,
    previous_execution_status TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending','accepted','rejected','withdrawn','cancelled','not_required')),
    decision_reason TEXT,
    decided_by TEXT,
    decided_grant_ref TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,project_id,handoff_id),
    UNIQUE (tenant_id,message_id),
    FOREIGN KEY (tenant_id,project_id,work_item_id)
      REFERENCES collaboration_work_links(tenant_id,project_id,work_item_id),
    FOREIGN KEY (tenant_id,message_id)
      REFERENCES delivery_messages(tenant_id,message_id)
      DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX IF NOT EXISTS collaboration_one_pending_handoff
    ON collaboration_handoffs(tenant_id,work_item_id) WHERE state='pending';
