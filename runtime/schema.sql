CREATE TABLE IF NOT EXISTS work_items (
    work_item_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('candidate','acceptance_ready','accepted')),
    execution_status TEXT NOT NULL DEFAULT 'ready' CHECK (execution_status IN ('ready','running','blocked','failed','cancelled')),
    revision INTEGER NOT NULL DEFAULT 0,
    source_baseline TEXT NOT NULL,
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime_schema_metadata (
    schema_name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    schema_checksum TEXT NOT NULL,
    adopted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS command_dedup (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    result_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key)
);
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS command_id TEXT;
UPDATE command_dedup SET command_id = idempotency_key WHERE command_id IS NULL;
ALTER TABLE command_dedup ALTER COLUMN command_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS command_dedup_command_id ON command_dedup(tenant_id, command_id);

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
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, work_item_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS accepted_state_revisions (
    tenant_id TEXT NOT NULL, work_item_id TEXT NOT NULL, revision INTEGER NOT NULL,
    baseline_ref TEXT NOT NULL, evidence_refs JSONB NOT NULL, review_ref TEXT NOT NULL,
    effect_refs JSONB NOT NULL, readback_refs JSONB NOT NULL, accepted_by TEXT, policy_version TEXT, parent_revision INTEGER, scope_id TEXT, valid_from TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, work_item_id, revision)
);
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS accepted_by TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS policy_version TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS parent_revision INTEGER;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS scope_id TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS domain_events (
    event_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    initiated_by TEXT NOT NULL,
    lineage_mode TEXT NOT NULL,
    command_id TEXT NOT NULL,
    resulting_revision INTEGER NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS leases (
    lease_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    owner_attempt_id TEXT NOT NULL,
    owner_runtime_id TEXT NOT NULL,
    authority_id TEXT NOT NULL DEFAULT 'acs-p1-authority',
    authority_incarnation TEXT NOT NULL,
    generation BIGINT NOT NULL,
    fencing_token TEXT NOT NULL,
    grant_ref TEXT NOT NULL,
    command_id TEXT,
    idempotency_key TEXT,
    scope_id TEXT NOT NULL DEFAULT 'local-scope',
    request_hash TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('granted','released','expired','revoked'))
);
ALTER TABLE leases ADD COLUMN IF NOT EXISTS command_id TEXT;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS scope_id TEXT DEFAULT 'local-scope';
ALTER TABLE leases ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE leases ADD COLUMN IF NOT EXISTS authority_id TEXT DEFAULT 'acs-p1-authority';
CREATE UNIQUE INDEX IF NOT EXISTS leases_command_identity ON leases(tenant_id, command_id) WHERE command_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS leases_idempotency_identity ON leases(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS leases_one_live_resource
    ON leases (tenant_id, resource_id) WHERE status = 'granted';

CREATE TABLE IF NOT EXISTS effects (
    effect_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    baseline_ref TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    fencing_token TEXT NOT NULL,
    generation BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('prepared','authorized','dispatched','uncertain','verified','failed')),
    readback_ref TEXT,
    grant_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE effects ADD COLUMN IF NOT EXISTS generation BIGINT DEFAULT 0;

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    observer_ref TEXT NOT NULL,
    source_class TEXT NOT NULL,
    baseline_ref TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    reviewer_ref TEXT NOT NULL,
    reviewer_grant_ref TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail')),
    evidence_ref TEXT NOT NULL,
    baseline_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reviewer_assignments (
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    reviewer_ref TEXT NOT NULL,
    reviewer_grant_ref TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','revoked')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, work_item_id, reviewer_ref)
);
