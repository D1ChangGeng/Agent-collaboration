-- Runtime schema 1.9 isolated candidate extension.
-- Integration requires the receiver-transport-owned Runtime schema 1.8 first.

CREATE TABLE IF NOT EXISTS native_response_observations (
    tenant_id TEXT NOT NULL,
    projection_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    binding_revision BIGINT NOT NULL,
    machine_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    boot_incarnation TEXT NOT NULL,
    accepted_revision BIGINT NOT NULL,
    accepted_state_digest TEXT NOT NULL CHECK(length(accepted_state_digest)=64),
    native_response_ref TEXT NOT NULL,
    native_outcome TEXT NOT NULL CHECK(native_outcome IN ('completed','failed','interrupted')),
    response_artifact_ref TEXT NOT NULL,
    response_digest TEXT NOT NULL CHECK(length(response_digest)=64),
    evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
    observed_at TIMESTAMPTZ NOT NULL,
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    disposition TEXT NOT NULL CHECK(disposition IN ('applied','fenced_late')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,projection_id),
    UNIQUE(tenant_id,receipt_id),
    UNIQUE(tenant_id,invocation_id),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
);

CREATE TABLE IF NOT EXISTS recovery_incidents (
    tenant_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    generation BIGINT NOT NULL CHECK(generation>=1),
    message_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL,
    target_scope_id TEXT NOT NULL,
    accepted_revision BIGINT NOT NULL CHECK(accepted_revision>=0),
    accepted_state_digest TEXT NOT NULL CHECK(length(accepted_state_digest)=64),
    expires_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'open','human_requested','manual_packet_committed','resolved_automatic',
        'resolved_manual','expired','cancelled'
    )),
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    applied_packet_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,incident_id),
    UNIQUE(tenant_id,message_id,generation)
);

CREATE UNIQUE INDEX IF NOT EXISTS recovery_incidents_one_active
    ON recovery_incidents(tenant_id,message_id)
    WHERE state IN ('open','human_requested','manual_packet_committed');

CREATE TABLE IF NOT EXISTS recovery_path_attempts (
    tenant_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('failed','unavailable','unsupported','budget_exhausted')),
    attempt_refs JSONB NOT NULL,
    evidence_refs JSONB NOT NULL,
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    PRIMARY KEY(tenant_id,incident_id,path_id),
    FOREIGN KEY(tenant_id,incident_id) REFERENCES recovery_incidents(tenant_id,incident_id)
);

CREATE TABLE IF NOT EXISTS human_bridge_requests (
    tenant_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    outbox_message_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,request_id),
    UNIQUE(tenant_id,incident_id),
    UNIQUE(tenant_id,outbox_message_id),
    FOREIGN KEY(tenant_id,incident_id) REFERENCES recovery_incidents(tenant_id,incident_id)
);

CREATE TABLE IF NOT EXISTS recovery_reprobes (
    tenant_id TEXT NOT NULL,
    reprobe_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    observation_ref TEXT NOT NULL,
    succeeded BOOLEAN NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('observed','fenced_late')),
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,reprobe_id),
    UNIQUE(tenant_id,incident_id,observation_ref),
    FOREIGN KEY(tenant_id,incident_id) REFERENCES recovery_incidents(tenant_id,incident_id)
);

CREATE TABLE IF NOT EXISTS human_bridge_packets (
    tenant_id TEXT NOT NULL,
    packet_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    incident_generation BIGINT NOT NULL,
    message_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL,
    target_scope_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('request','response')),
    expected_accepted_revision BIGINT NOT NULL,
    accepted_state_digest TEXT NOT NULL CHECK(length(accepted_state_digest)=64),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64),
    expires_at TIMESTAMPTZ NOT NULL,
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    disposition TEXT NOT NULL CHECK(disposition IN ('committed','fenced_late')),
    normal_outbox_message_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,packet_id),
    FOREIGN KEY(tenant_id,incident_id) REFERENCES recovery_incidents(tenant_id,incident_id)
);

CREATE TABLE IF NOT EXISTS human_bridge_normal_receipts (
    tenant_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    packet_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('request','response')),
    layer TEXT NOT NULL CHECK(layer IN ('target_inbox_committed','response_received')),
    payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64),
    evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,receipt_id),
    UNIQUE(tenant_id,incident_id,packet_id),
    FOREIGN KEY(tenant_id,incident_id) REFERENCES recovery_incidents(tenant_id,incident_id),
    FOREIGN KEY(tenant_id,packet_id) REFERENCES human_bridge_packets(tenant_id,packet_id)
);

CREATE TABLE IF NOT EXISTS recovery_audit_events (
    audit_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    incident_id TEXT,
    projection_id TEXT,
    event_type TEXT NOT NULL,
    command_id TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    grant_ref TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS native_response_consumptions (
    tenant_id TEXT NOT NULL,
    projection_id TEXT NOT NULL,
    consumer_command_id TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,projection_id),
    UNIQUE(tenant_id,consumer_command_id),
    FOREIGN KEY(tenant_id,projection_id)
      REFERENCES native_response_observations(tenant_id,projection_id)
);
CREATE TABLE IF NOT EXISTS recovery_command_claims (
    tenant_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    canonical_digest TEXT NOT NULL CHECK(length(canonical_digest)=64),
    state TEXT NOT NULL CHECK(state IN ('pending','completed')),
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,command_id),
    UNIQUE(tenant_id,idempotency_key)
);
