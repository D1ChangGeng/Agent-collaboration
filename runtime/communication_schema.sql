-- Explicitly adopted communication indexes. Content lives in packet_json.
ALTER TABLE delivery_messages ALTER COLUMN endpoint_id DROP NOT NULL;
ALTER TABLE delivery_messages ALTER COLUMN binding_revision DROP NOT NULL;
CREATE TABLE IF NOT EXISTS communication_clients (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    address TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,address),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS communication_messages (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    sequence BIGSERIAL NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS communication_inbox ON communication_messages(tenant_id,project_id,recipient,sequence);
CREATE INDEX IF NOT EXISTS communication_sent ON communication_messages(tenant_id,project_id,sender,sequence);
CREATE TABLE IF NOT EXISTS communication_replies (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    reply_id TEXT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,request_id,reply_id),
    FOREIGN KEY(tenant_id,project_id,request_id)
        REFERENCES communication_messages(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id,reply_id)
        REFERENCES communication_messages(tenant_id,project_id,message_id)
);
CREATE TABLE IF NOT EXISTS communication_waits (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    waiter_id TEXT NOT NULL,
    address TEXT NOT NULL,
    request_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(tenant_id,project_id,waiter_id,request_id),
    FOREIGN KEY(tenant_id,project_id,request_id)
        REFERENCES communication_messages(tenant_id,project_id,message_id)
);
CREATE TABLE IF NOT EXISTS communication_notices (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    sequence BIGSERIAL NOT NULL UNIQUE,
    recipient TEXT NOT NULL,
    state TEXT NOT NULL,
    code TEXT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,message_id,recipient),
    FOREIGN KEY(tenant_id,project_id,message_id)
        REFERENCES communication_messages(tenant_id,project_id,message_id)
);
