-- Current communication Authority: identity, transport, receipts and durable fences.
-- Legacy event/dedup provenance columns remain readable; no task objects are created.
-- Explicit operator adoption only. This DDL never rewrites stored rows.
CREATE TABLE IF NOT EXISTS runtime_schema_metadata (
    schema_name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    schema_checksum TEXT NOT NULL,
    adopted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS command_dedup (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_id TEXT,
    payload_hash TEXT NOT NULL,
    hash_version TEXT NOT NULL DEFAULT 'legacy-unclassified',
    canonical_hash TEXT,
    migration_state TEXT NOT NULL DEFAULT 'legacy',
    legacy_command_id TEXT,
    legacy_record JSONB,
    replay_policy TEXT NOT NULL DEFAULT 'verify_legacy_hash',
    quarantine_reason TEXT,
    result_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS command_dedup_command_id ON command_dedup(tenant_id,command_id);

CREATE TABLE IF NOT EXISTS authority_instances (
    authority_id TEXT NOT NULL, authority_incarnation TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (authority_id, authority_incarnation)
);

CREATE TABLE IF NOT EXISTS scopes (
    scope_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
    policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('active','revoked'))
);

CREATE TABLE IF NOT EXISTS agent_slots (
    agent_slot_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
    status TEXT NOT NULL CHECK (status IN ('active','revoked'))
);

CREATE TABLE IF NOT EXISTS grants (
    grant_ref TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_ref TEXT NOT NULL,
    authority_id TEXT NOT NULL, authority_incarnation TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id), permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS domain_events (
    event_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    initiated_by TEXT NOT NULL,
    lineage_mode TEXT NOT NULL,
    command_id TEXT NOT NULL,
    resulting_revision INTEGER NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_hash_version TEXT NOT NULL DEFAULT 'v1',
    canonical_hash TEXT,
    target_kind TEXT NOT NULL DEFAULT 'message',
    target_id TEXT NOT NULL,
    related_work_item_id TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload JSONB NOT NULL,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, message_id)
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_workflow_id TEXT NOT NULL,
    provider_run_id TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inbox_messages (
    tenant_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    target_agent_slot_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    receipt_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, message_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS authority_instances_one_active
    ON authority_instances(authority_id) WHERE status='active';

CREATE OR REPLACE FUNCTION acs_domain_event_target() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.target_id IS NULL THEN NEW.target_id := NEW.work_item_id; END IF;
    IF NEW.target_kind='work_item' AND (NEW.work_item_id IS NULL OR NEW.target_id<>NEW.work_item_id) THEN
        RAISE EXCEPTION 'WorkItem event target differs' USING ERRCODE='23514';
    END IF;
    IF NEW.target_kind<>'work_item' AND NEW.work_item_id IS NOT NULL THEN
        RAISE EXCEPTION 'non-WorkItem event cannot impersonate a WorkItem event' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS acs_domain_event_target ON domain_events;

CREATE TRIGGER acs_domain_event_target BEFORE INSERT OR UPDATE ON domain_events
FOR EACH ROW EXECUTE FUNCTION acs_domain_event_target();

CREATE TABLE IF NOT EXISTS enrolled_nodes (
    tenant_id TEXT NOT NULL, node_id TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES scopes(scope_id), agent_slot_id TEXT NOT NULL REFERENCES agent_slots(agent_slot_id),
    observer_ref TEXT NOT NULL, observer_grant_ref TEXT NOT NULL REFERENCES grants(grant_ref),
    authority_id TEXT NOT NULL, authority_incarnation TEXT NOT NULL,
    revision BIGINT NOT NULL, current_binding_revision BIGINT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','revoked')),
    enrolled_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revoked_at TIMESTAMPTZ, revocation_policy TEXT,
    PRIMARY KEY(tenant_id,node_id)
);

CREATE TABLE IF NOT EXISTS enrolled_node_keys (
    key_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, node_id TEXT NOT NULL,
    public_key TEXT NOT NULL CHECK(public_key ~ '^[a-f0-9]{64}$'),
    fingerprint TEXT NOT NULL UNIQUE CHECK(fingerprint ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), retired_at TIMESTAMPTZ,
    FOREIGN KEY(tenant_id,node_id) REFERENCES enrolled_nodes(tenant_id,node_id)
);

CREATE TABLE IF NOT EXISTS enrolled_node_bindings (
    tenant_id TEXT NOT NULL, node_id TEXT NOT NULL, binding_revision BIGINT NOT NULL,
    key_id TEXT NOT NULL REFERENCES enrolled_node_keys(key_id), machine_id TEXT NOT NULL, boot_incarnation TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), expires_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ, command_id TEXT NOT NULL, operation_id TEXT NOT NULL, event_id TEXT,
    PRIMARY KEY(tenant_id,node_id,binding_revision), UNIQUE(tenant_id,node_id,boot_incarnation),
    FOREIGN KEY(tenant_id,node_id) REFERENCES enrolled_nodes(tenant_id,node_id)
);

CREATE TABLE IF NOT EXISTS enrolled_runtimes (
    tenant_id TEXT NOT NULL, runtime_id TEXT NOT NULL, node_id TEXT NOT NULL, node_binding_revision BIGINT NOT NULL,
    node_boot_incarnation TEXT NOT NULL, scope_id TEXT NOT NULL, agent_slot_id TEXT NOT NULL,
    producer_ref TEXT NOT NULL, producer_grant_ref TEXT NOT NULL,
    observer_ref TEXT NOT NULL, observer_grant_ref TEXT NOT NULL,
    authority_id TEXT NOT NULL, authority_incarnation TEXT NOT NULL, provider TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1, status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), expires_at TIMESTAMPTZ NOT NULL, retired_at TIMESTAMPTZ,
    command_id TEXT NOT NULL, operation_id TEXT NOT NULL, event_id TEXT,
    PRIMARY KEY(tenant_id,runtime_id),
    FOREIGN KEY(tenant_id,node_id,node_binding_revision)
      REFERENCES enrolled_node_bindings(tenant_id,node_id,binding_revision)
);

CREATE TABLE IF NOT EXISTS enrolled_node_challenges (
    challenge_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, node_id TEXT NOT NULL, node_binding_revision BIGINT NOT NULL,
    purpose TEXT NOT NULL, purpose_command_id TEXT NOT NULL, purpose_hash TEXT NOT NULL,
    message_hex TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), consumed_by TEXT,
    issuance_command_id TEXT NOT NULL, issuance_operation_id TEXT NOT NULL,
    FOREIGN KEY(tenant_id,node_id,node_binding_revision)
      REFERENCES enrolled_node_bindings(tenant_id,node_id,binding_revision)
);

CREATE TABLE IF NOT EXISTS enrolled_node_command_proofs (
    challenge_id TEXT PRIMARY KEY REFERENCES enrolled_node_challenges(challenge_id),
    tenant_id TEXT NOT NULL, node_id TEXT NOT NULL, node_binding_revision BIGINT NOT NULL,
    command_id TEXT NOT NULL, purpose TEXT NOT NULL, signature TEXT NOT NULL,
    command_json JSONB NOT NULL, input_json JSONB NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS enrolled_node_proof_command_lookup
    ON enrolled_node_command_proofs(tenant_id,command_id);

CREATE TABLE IF NOT EXISTS enrollment_command_views (
    tenant_id TEXT NOT NULL, command_id TEXT NOT NULL, view_json JSONB NOT NULL,
    PRIMARY KEY(tenant_id,command_id)
);

CREATE TABLE IF NOT EXISTS delivery_endpoints (
    tenant_id TEXT NOT NULL, endpoint_id TEXT NOT NULL,
    revision BIGINT NOT NULL, scope_id TEXT NOT NULL, agent_slot_id TEXT NOT NULL,
    machine_id TEXT NOT NULL, node_id TEXT NOT NULL, boot_incarnation TEXT NOT NULL,
    supports_invoke BOOLEAN NOT NULL, evidence_class TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, status TEXT NOT NULL DEFAULT 'active',
    command_id TEXT NOT NULL, operation_id TEXT NOT NULL,
    PRIMARY KEY(tenant_id,endpoint_id)
);

CREATE TABLE IF NOT EXISTS delivery_messages (
    tenant_id TEXT NOT NULL, message_id TEXT NOT NULL, command_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
    endpoint_id TEXT NOT NULL, binding_revision BIGINT NOT NULL,
    packet_json JSONB NOT NULL, command_json JSONB NOT NULL, canonical_hash TEXT NOT NULL,
    envelope_json JSONB NOT NULL, envelope_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','delivering','retry_wait','delivered','uncertain','expired','blocked','budget_exhausted')),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    deadline TIMESTAMPTZ NOT NULL, maximum_attempts INTEGER NOT NULL CHECK(maximum_attempts BETWEEN 1 AND 8),
    retry_delay_seconds INTEGER NOT NULL CHECK(retry_delay_seconds BETWEEN 1 AND 30),
    last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    policy_hash TEXT NOT NULL, accepted_state_digest TEXT NOT NULL,
    receipt_high_water TEXT NOT NULL DEFAULT 'accepted_by_authority'
        CHECK(receipt_high_water IN ('accepted_by_authority','target_inbox_committed','runtime_dispatched','runtime_acknowledged','response_received')),
    activation_node_id TEXT, activation_machine_id TEXT,
    activation_dispatch_id TEXT, activation_receipt_id TEXT,
    PRIMARY KEY(tenant_id,message_id), UNIQUE(tenant_id,command_id),
    FOREIGN KEY(tenant_id,endpoint_id) REFERENCES delivery_endpoints(tenant_id,endpoint_id)
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    tenant_id TEXT NOT NULL, message_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE, operation_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL, selection_revision BIGINT NOT NULL, connection_ref TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), finished_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'prepared','runtime_dispatched','interrupted','retry_wait','delivered',
        'uncertain','expired','blocked','budget_exhausted'
    )),
    error_code TEXT,
    selection_json JSONB NOT NULL, selection_digest TEXT NOT NULL,
    selection_history_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    invocation_json JSONB, invocation_digest TEXT,
    dispatch_id TEXT, runtime_dispatched_receipt_id TEXT,
    PRIMARY KEY(tenant_id,message_id,ordinal),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
);

ALTER TABLE delivery_attempts
    ADD COLUMN IF NOT EXISTS selection_history_json JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS delivery_attempts_one_open
    ON delivery_attempts(tenant_id,message_id) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS delivery_receipts (
    tenant_id TEXT NOT NULL, message_id TEXT NOT NULL, receipt_id TEXT NOT NULL,
    layer TEXT NOT NULL, attempt_id TEXT, dispatch_id TEXT,
    evidence_json JSONB NOT NULL, observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,message_id,layer), UNIQUE(tenant_id,receipt_id),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
);

CREATE TABLE IF NOT EXISTS authority_transport_keys (
    tenant_id TEXT NOT NULL,
    authority_id TEXT NOT NULL,
    authority_incarnation TEXT NOT NULL,
    key_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    public_key TEXT NOT NULL CHECK(public_key ~ '^[a-f0-9]{64}$'),
    fingerprint TEXT NOT NULL CHECK(fingerprint ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ,
    command_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    PRIMARY KEY(tenant_id,key_id),
    UNIQUE(tenant_id,authority_id,authority_incarnation,revision),
    FOREIGN KEY(authority_id,authority_incarnation)
      REFERENCES authority_instances(authority_id,authority_incarnation)
);

CREATE UNIQUE INDEX IF NOT EXISTS authority_transport_keys_one_active
    ON authority_transport_keys(tenant_id,authority_id,authority_incarnation)
    WHERE status='active';

CREATE TABLE IF NOT EXISTS deployment_connection_refs (
    tenant_id TEXT NOT NULL,
    connection_ref TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    locator_host TEXT NOT NULL,
    locator_port INTEGER NOT NULL CHECK(locator_port BETWEEN 1 AND 65535),
    route_class TEXT NOT NULL CHECK(route_class IN ('loopback','private','tunnel')),
    policy_digest TEXT NOT NULL CHECK(policy_digest ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(tenant_id,connection_ref)
);

CREATE TABLE IF NOT EXISTS delivery_endpoint_registrations (
    tenant_id TEXT NOT NULL,
    authority_id TEXT NOT NULL,
    authority_incarnation TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    endpoint_revision BIGINT NOT NULL CHECK(endpoint_revision >= 1),
    registration_id TEXT NOT NULL,
    connection_ref TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_binding_revision BIGINT NOT NULL,
    runtime_id TEXT NOT NULL,
    runtime_revision BIGINT NOT NULL,
    machine_id TEXT NOT NULL,
    boot_incarnation TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    tls_certificate_sha256 TEXT NOT NULL CHECK(tls_certificate_sha256 ~ '^[a-f0-9]{64}$'),
    config_sha256 TEXT NOT NULL CHECK(config_sha256 ~ '^[a-f0-9]{64}$'),
    node_key_id TEXT NOT NULL,
    registration_json JSONB NOT NULL CHECK(jsonb_typeof(registration_json)='object'),
    registration_sha256 TEXT NOT NULL CHECK(registration_sha256 ~ '^[a-f0-9]{64}$'),
    registration_signature TEXT NOT NULL CHECK(registration_signature ~ '^[a-f0-9]{128}$'),
    proof_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','retired','revoked')),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    command_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    PRIMARY KEY(tenant_id,endpoint_id,endpoint_revision),
    UNIQUE(tenant_id,registration_id),
    FOREIGN KEY(tenant_id,connection_ref)
      REFERENCES deployment_connection_refs(tenant_id,connection_ref),
    FOREIGN KEY(tenant_id,node_id,node_binding_revision)
      REFERENCES enrolled_node_bindings(tenant_id,node_id,binding_revision),
    FOREIGN KEY(tenant_id,runtime_id)
      REFERENCES enrolled_runtimes(tenant_id,runtime_id),
    FOREIGN KEY(node_key_id) REFERENCES enrolled_node_keys(key_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS delivery_endpoint_registrations_one_active
    ON delivery_endpoint_registrations(tenant_id,endpoint_id) WHERE status='active';

CREATE TABLE IF NOT EXISTS delivery_transport_admissions (
    tenant_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    nonce TEXT NOT NULL CHECK(nonce ~ '^[a-f0-9]{64}$'),
    purpose TEXT NOT NULL CHECK(purpose IN (
      'delivery.prepare','delivery.dispatch','delivery.readback','delivery.recover'
    )),
    authority_id TEXT NOT NULL,
    authority_incarnation TEXT NOT NULL,
    authority_key_id TEXT NOT NULL,
    authority_key_revision BIGINT NOT NULL,
    method TEXT NOT NULL CHECK(method='POST'),
    path TEXT NOT NULL,
    message_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    endpoint_revision BIGINT NOT NULL,
    runtime_id TEXT NOT NULL,
    runtime_revision BIGINT NOT NULL,
    node_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    admitted_boot_incarnation TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    accepted_revision BIGINT CHECK(accepted_revision >= 0),
    accepted_state_digest TEXT NOT NULL CHECK(accepted_state_digest ~ '^[a-f0-9]{64}$'),
    envelope_digest TEXT NOT NULL CHECK(envelope_digest ~ '^[a-f0-9]{64}$'),
    selection_digest TEXT NOT NULL CHECK(selection_digest ~ '^[a-f0-9]{64}$'),
    invocation_digest TEXT NOT NULL CHECK(invocation_digest ~ '^[a-f0-9]{64}$'),
    journal_generation BIGINT NOT NULL CHECK(journal_generation >= 1),
    body_sha256 TEXT NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
    admission_sha256 TEXT NOT NULL CHECK(admission_sha256 ~ '^[a-f0-9]{64}$'),
    signed_request_sha256 TEXT NOT NULL CHECK(signed_request_sha256 ~ '^[a-f0-9]{64}$'),
    admission_json JSONB NOT NULL CHECK(jsonb_typeof(admission_json)='object'),
    body_json JSONB NOT NULL CHECK(jsonb_typeof(body_json)='object'),
    signed_request_json JSONB NOT NULL CHECK(jsonb_typeof(signed_request_json)='object'),
    signature TEXT NOT NULL CHECK(signature ~ '^[a-f0-9]{128}$'),
    state TEXT NOT NULL CHECK(state IN (
      'issued','prepared','runtime_dispatched','completed','uncertain','blocked','recovery_superseded'
    )),
    issued_at TIMESTAMPTZ NOT NULL,
    deadline TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,request_id),
    UNIQUE(tenant_id,nonce),
    FOREIGN KEY(tenant_id,authority_key_id)
      REFERENCES authority_transport_keys(tenant_id,key_id),
    FOREIGN KEY(tenant_id,message_id)
      REFERENCES delivery_messages(tenant_id,message_id),
    FOREIGN KEY(tenant_id,endpoint_id,endpoint_revision)
      REFERENCES delivery_endpoint_registrations(tenant_id,endpoint_id,endpoint_revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS delivery_transport_one_active_dispatch
    ON delivery_transport_admissions(tenant_id,operation_id,attempt_id,dispatch_id)
    WHERE purpose IN ('delivery.dispatch','delivery.recover')
      AND state IN ('issued','runtime_dispatched','completed','uncertain');

CREATE UNIQUE INDEX IF NOT EXISTS delivery_transport_one_prepare
    ON delivery_transport_admissions(tenant_id,operation_id,attempt_id,dispatch_id)
    WHERE purpose='delivery.prepare';

CREATE TABLE IF NOT EXISTS delivery_receiver_receipts (
    tenant_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_request_id TEXT NOT NULL,
    readback_request_id TEXT,
    challenge_nonce TEXT NOT NULL CHECK(challenge_nonce ~ '^[a-f0-9]{64}$'),
    node_id TEXT NOT NULL,
    node_binding_revision BIGINT NOT NULL,
    node_key_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    state TEXT NOT NULL,
    receipt_json JSONB NOT NULL,
    receipt_sha256 TEXT NOT NULL CHECK(receipt_sha256 ~ '^[a-f0-9]{64}$'),
    signed_receipt_sha256 TEXT NOT NULL CHECK(signed_receipt_sha256 ~ '^[a-f0-9]{64}$'),
    signed_receipt_json JSONB NOT NULL CHECK(jsonb_typeof(signed_receipt_json)='object'),
    signature TEXT NOT NULL CHECK(signature ~ '^[a-f0-9]{128}$'),
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,receipt_id),
    UNIQUE(tenant_id,request_id,receipt_sha256),
    FOREIGN KEY(tenant_id,request_id)
      REFERENCES delivery_transport_admissions(tenant_id,request_id),
    FOREIGN KEY(tenant_id,node_id,node_binding_revision)
      REFERENCES enrolled_node_bindings(tenant_id,node_id,binding_revision),
    FOREIGN KEY(node_key_id) REFERENCES enrolled_node_keys(key_id)
);

CREATE TABLE IF NOT EXISTS grant_delegations (
    grant_ref TEXT PRIMARY KEY REFERENCES grants(grant_ref),
    parent_grant_ref TEXT NOT NULL REFERENCES grants(grant_ref),
    tenant_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    parent_policy_digest TEXT NOT NULL CHECK(length(parent_policy_digest)=64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK(grant_ref <> parent_grant_ref)
);

CREATE OR REPLACE FUNCTION acs_notify_domain_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('acs_domain_change', json_build_object(
        'schema',TG_TABLE_SCHEMA,'tenant_id',NEW.tenant_id,'event_id',NEW.event_id)::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS acs_notify_domain_change ON domain_events;

CREATE TRIGGER acs_notify_domain_change AFTER INSERT ON domain_events
FOR EACH ROW EXECUTE FUNCTION acs_notify_domain_change();

CREATE OR REPLACE FUNCTION acs_notify_receipt_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('acs_receipt_change', json_build_object(
        'schema',TG_TABLE_SCHEMA,'tenant_id',NEW.tenant_id,'message_id',NEW.message_id)::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS acs_notify_receipt_change ON delivery_receipts;

CREATE TRIGGER acs_notify_receipt_change AFTER INSERT ON delivery_receipts
FOR EACH ROW EXECUTE FUNCTION acs_notify_receipt_change();

ALTER TABLE delivery_transport_admissions DROP CONSTRAINT IF EXISTS delivery_transport_admissions_purpose_check;

ALTER TABLE delivery_transport_admissions ADD CONSTRAINT delivery_transport_admissions_purpose_check
    CHECK(purpose IN ('delivery.prepare','delivery.dispatch','delivery.readback','delivery.recover','delivery.readiness'));

ALTER TABLE delivery_messages ALTER COLUMN deadline DROP NOT NULL;

ALTER TABLE delivery_attempts ALTER COLUMN deadline DROP NOT NULL;

ALTER TABLE grants ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE grants ADD COLUMN IF NOT EXISTS identity_only BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE enrolled_node_bindings ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE enrolled_runtimes ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE delivery_endpoints ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE delivery_endpoint_registrations ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE deployment_connection_refs ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE authority_transport_keys ALTER COLUMN expires_at DROP NOT NULL;

ALTER TABLE delivery_endpoint_registrations ALTER COLUMN proof_ref DROP NOT NULL;

ALTER TABLE delivery_transport_admissions ALTER COLUMN deadline DROP NOT NULL;

ALTER TABLE delivery_transport_admissions ALTER COLUMN accepted_revision DROP NOT NULL;

CREATE TABLE IF NOT EXISTS owner_node_commands (
    tenant_id TEXT NOT NULL, command_id TEXT NOT NULL, node_id TEXT NOT NULL,
    node_binding_revision BIGINT NOT NULL, purpose TEXT NOT NULL,
    command_json JSONB NOT NULL, input_json JSONB NOT NULL,
    canonical_hash TEXT NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, command_id)
);
