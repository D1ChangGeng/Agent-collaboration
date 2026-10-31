-- Additive, explicit operator adoption. Existing messages and notices remain intact.
CREATE TABLE IF NOT EXISTS communication_supervisors (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL REFERENCES agent_slots(agent_slot_id),
    manager_address TEXT NOT NULL,
    PRIMARY KEY(tenant_id,project_id,agent_slot_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS communication_notice_routes (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    source_slot_id TEXT,
    native_requested BOOLEAN NOT NULL,
    delivery_message_id TEXT UNIQUE,
    last_error TEXT,
    PRIMARY KEY(tenant_id,project_id,message_id,recipient),
    FOREIGN KEY(tenant_id,project_id,message_id,recipient)
        REFERENCES communication_notices(tenant_id,project_id,message_id,recipient),
    FOREIGN KEY(tenant_id,delivery_message_id) REFERENCES delivery_messages(tenant_id,message_id)
        DEFERRABLE INITIALLY DEFERRED
);
