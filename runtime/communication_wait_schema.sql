-- Operational ingress facts only. Message bodies and reply relationships keep
-- their existing Authority; legacy active_wait receipts are never rewritten.
CREATE TABLE IF NOT EXISTS communication_wait_ingress (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    request_ids TEXT[] NOT NULL CHECK(cardinality(request_ids) BETWEEN 1 AND 32),
    state TEXT NOT NULL CHECK(state IN ('reserved','selected','released')),
    waiter_ref TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    selected_at TIMESTAMPTZ,
    PRIMARY KEY(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id,message_id)
        REFERENCES communication_messages(tenant_id,project_id,message_id)
);
CREATE INDEX IF NOT EXISTS communication_wait_ingress_due
    ON communication_wait_ingress(tenant_id,expires_at) WHERE state='reserved';
