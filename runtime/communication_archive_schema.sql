-- Derived routing facts for original packets, never converted Agent messages.
CREATE TABLE IF NOT EXISTS communication_archives (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    source_schema TEXT NOT NULL CHECK(source_schema='acs-delivery/1'),
    source_hash TEXT NOT NULL,
    author_principal_ref TEXT,
    recipient_slot_id TEXT,
    response_initiator_ref TEXT,
    association_source TEXT NOT NULL CHECK(association_source='stored_project_work_link'),
    PRIMARY KEY(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
);
