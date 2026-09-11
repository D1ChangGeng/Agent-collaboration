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
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS command_id TEXT;
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS hash_version TEXT NOT NULL DEFAULT 'legacy-unclassified';
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS canonical_hash TEXT;
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS migration_state TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS legacy_command_id TEXT;
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS legacy_record JSONB;
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS replay_policy TEXT NOT NULL DEFAULT 'verify_legacy_hash';
ALTER TABLE command_dedup ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
ALTER TABLE command_dedup ALTER COLUMN command_id DROP NOT NULL;
ALTER TABLE command_dedup ALTER COLUMN hash_version SET DEFAULT 'legacy-unclassified';
ALTER TABLE command_dedup ALTER COLUMN replay_policy SET DEFAULT 'verify_legacy_hash';

-- This statement atomically locks, classifies, quarantines and reindexes legacy
-- rows. Current/v2 rows are read only for conflicts and never receive snapshots.
DO $command_dedup_migration$
BEGIN
    LOCK TABLE command_dedup IN ACCESS EXCLUSIVE MODE;

    IF EXISTS (
        SELECT 1 FROM command_dedup
        WHERE migration_state = 'legacy' AND hash_version IS DISTINCT FROM 'v2'
    ) THEN
        -- Rebuild in this transaction so a retiring legacy identity cannot
        -- produce an intermediate uniqueness violation during classification.
        DROP INDEX IF EXISTS command_dedup_command_id;

        WITH legacy AS MATERIALIZED (
            SELECT d.*,
                COALESCE(jsonb_typeof(d.result_json) = 'object', FALSE) AS result_is_object,
                CASE WHEN jsonb_typeof(d.result_json) = 'object'
                    THEN d.result_json ? 'command_id' ELSE FALSE END AS result_has_id,
                CASE WHEN jsonb_typeof(d.result_json) = 'object'
                       AND jsonb_typeof(d.result_json -> 'command_id') = 'string'
                    THEN d.result_json ->> 'command_id' END AS result_command_id
            FROM command_dedup AS d
            WHERE d.migration_state = 'legacy'
              AND d.hash_version IS DISTINCT FROM 'v2'
        ), validated AS MATERIALIZED (
            SELECT l.*,
                (
                    l.command_id IS NOT NULL
                    AND char_length(l.command_id) BETWEEN 1 AND 256
                    AND l.command_id !~ U&'[\0001-\001F\007F-\009F]'
                    AND l.command_id !~ U&'^[\0020\00A0\1680\2000-\200A\2028\2029\202F\205F\3000]*$'
                ) AS column_id_valid,
                (
                    l.result_command_id IS NOT NULL
                    AND char_length(l.result_command_id) BETWEEN 1 AND 256
                    AND l.result_command_id !~ U&'[\0001-\001F\007F-\009F]'
                    AND l.result_command_id !~ U&'^[\0020\00A0\1680\2000-\200A\2028\2029\202F\205F\3000]*$'
                ) AS result_id_valid
            FROM legacy AS l
        ), candidates AS MATERIALIZED (
            -- Keep both independently valid claims when a row contradicts
            -- itself, so neither claim silently licenses another legacy row.
            SELECT DISTINCT v.tenant_id, v.idempotency_key, claim.command_id
            FROM validated AS v
            CROSS JOIN LATERAL (
                VALUES
                    (CASE WHEN v.column_id_valid THEN v.command_id END),
                    (CASE WHEN v.result_id_valid THEN v.result_command_id END)
            ) AS claim(command_id)
            WHERE claim.command_id IS NOT NULL
        ), duplicate_ids AS MATERIALIZED (
            SELECT tenant_id, command_id
            FROM candidates
            GROUP BY tenant_id, command_id
            HAVING count(*) > 1
        ), retained_claims AS MATERIALIZED (
            SELECT DISTINCT d.tenant_id, claim.command_id
            FROM command_dedup AS d
            CROSS JOIN LATERAL (
                VALUES
                    (d.command_id),
                    (CASE WHEN d.migration_state = 'quarantined' THEN d.legacy_command_id END),
                    (CASE WHEN d.migration_state = 'quarantined'
                               AND jsonb_typeof(d.legacy_record -> 'command_id') = 'string'
                        THEN d.legacy_record ->> 'command_id' END),
                    (CASE WHEN d.migration_state = 'quarantined'
                               AND jsonb_typeof(d.legacy_record -> 'result_json' -> 'command_id') = 'string'
                        THEN d.legacy_record -> 'result_json' ->> 'command_id' END)
            ) AS claim(command_id)
            WHERE (d.migration_state IS DISTINCT FROM 'legacy' OR d.hash_version = 'v2')
              AND claim.command_id IS NOT NULL
              AND char_length(claim.command_id) BETWEEN 1 AND 256
              AND claim.command_id !~ U&'[\0001-\001F\007F-\009F]'
              AND claim.command_id !~ U&'^[\0020\00A0\1680\2000-\200A\2028\2029\202F\205F\3000]*$'
        ), conflicting_rows AS MATERIALIZED (
            SELECT DISTINCT c.tenant_id, c.idempotency_key
            FROM candidates AS c
            WHERE EXISTS (
                SELECT 1 FROM duplicate_ids AS x
                WHERE x.tenant_id = c.tenant_id AND x.command_id = c.command_id
            ) OR EXISTS (
                SELECT 1 FROM retained_claims AS retained
                WHERE retained.tenant_id = c.tenant_id
                  AND retained.command_id = c.command_id
            )
        ), classified AS MATERIALIZED (
            SELECT v.*,
                CASE WHEN v.column_id_valid THEN v.command_id
                     WHEN v.result_id_valid THEN v.result_command_id END AS original_command_id,
                CASE
                    WHEN COALESCE(v.hash_version, 'legacy-unclassified') NOT IN
                        ('legacy-unclassified', 'v1', '1', 'e55-v0', '912-v1')
                        THEN 'legacy row has unknown hash_version'
                    WHEN v.payload_hash IS NULL OR v.payload_hash !~ '^[a-f0-9]{64}$'
                        THEN 'legacy payload_hash is missing or malformed'
                    WHEN NOT v.result_is_object
                        THEN 'legacy result_json is not an object'
                    WHEN v.result_has_id AND NOT v.result_id_valid
                        THEN 'legacy result command_id is malformed'
                    WHEN v.command_id IS NOT NULL AND NOT v.column_id_valid
                        THEN 'recorded legacy command_id is malformed'
                    WHEN v.column_id_valid AND v.result_id_valid
                         AND v.command_id <> v.result_command_id
                        THEN 'recorded command_id conflicts with result command_id'
                    WHEN NOT v.column_id_valid AND NOT v.result_id_valid
                        THEN 'legacy row has no recorded original command_id'
                    WHEN v.column_id_valid AND v.command_id = v.idempotency_key
                         AND NOT v.result_id_valid
                        THEN 'legacy command_id is indistinguishable from idempotency_key'
                    WHEN EXISTS (
                        SELECT 1 FROM conflicting_rows AS x
                        WHERE x.tenant_id = v.tenant_id
                          AND x.idempotency_key = v.idempotency_key
                    )
                        THEN 'legacy command_id conflicts within tenant or with a retained row'
                    ELSE NULL
                END AS rejection_reason
            FROM validated AS v
        )
        UPDATE command_dedup AS d
        SET
            -- Preserve the complete pre-update row once, including every
            -- recorded identity, original JSON result and original hash.
            legacy_record = COALESCE(d.legacy_record, to_jsonb(d) - 'legacy_record'),
            legacy_command_id = COALESCE(
                d.legacy_command_id, d.command_id, c.result_command_id
            ),
            hash_version = COALESCE(d.hash_version, 'legacy-unclassified'),
            command_id = CASE WHEN c.rejection_reason IS NULL
                THEN c.original_command_id ELSE NULL END,
            migration_state = CASE WHEN c.rejection_reason IS NULL
                THEN 'migrated' ELSE 'quarantined' END,
            replay_policy = CASE WHEN c.rejection_reason IS NULL
                THEN 'verify_legacy_hash' ELSE 'quarantine' END,
            quarantine_reason = c.rejection_reason
        FROM classified AS c
        WHERE d.tenant_id = c.tenant_id
          AND d.idempotency_key = c.idempotency_key
          AND d.migration_state = 'legacy'
          AND d.hash_version IS DISTINCT FROM 'v2';
    END IF;

    CREATE UNIQUE INDEX IF NOT EXISTS command_dedup_command_id
        ON command_dedup(tenant_id, command_id);
END
$command_dedup_migration$;

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
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS producer_ref TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS runtime_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS scope_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS grant_ref TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS authority_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS authority_incarnation TEXT;
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
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS candidate_ref TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS evidence_bundle_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS policy_digest TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS readback_digest TEXT;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS unresolved_items JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE accepted_state_revisions ADD COLUMN IF NOT EXISTS readiness_snapshot BOOLEAN NOT NULL DEFAULT false;

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
ALTER TABLE domain_events ADD COLUMN IF NOT EXISTS command_hash_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE domain_events ADD COLUMN IF NOT EXISTS canonical_hash TEXT;

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
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS bundle_ref TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS candidate_ref TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS execution_receipt_ref TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS evidence_state TEXT NOT NULL DEFAULT 'incomplete';
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS producer_ref TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS attempt_id TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS command_id TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS operation_id TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS event_id TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS test_exit_code INTEGER;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS readback_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS scope_id TEXT;

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_ref TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    digest TEXT NOT NULL CHECK (digest ~ '^sha256:[a-f0-9]{64}$'),
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    kind TEXT NOT NULL,
    media_type TEXT NOT NULL,
    immutable BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, scope_id, digest)
);

CREATE TABLE IF NOT EXISTS execution_receipts (
    receipt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    producer_ref TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    source_baseline TEXT NOT NULL,
    source_class TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    exit_code INTEGER,
    signal INTEGER,
    os_name TEXT NOT NULL,
    os_arch TEXT NOT NULL,
    toolchain TEXT NOT NULL,
    command_line JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    readback_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_artifact_ref TEXT,
    receipt_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_bundles (
    bundle_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    baseline_ref TEXT NOT NULL,
    source_class TEXT NOT NULL,
    observer_ref TEXT NOT NULL,
    producer_ref TEXT NOT NULL,
    receipt_id TEXT NOT NULL REFERENCES execution_receipts(receipt_id),
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    readback_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    bundle_json JSONB NOT NULL,
    evidence_state TEXT NOT NULL DEFAULT 'incomplete',
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
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS candidate_ref TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS evidence_set_hash TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS authority_incarnation TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS assignment_revision BIGINT;

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
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS assignment_revision BIGINT NOT NULL DEFAULT 0;
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS command_id TEXT;
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS operation_id TEXT;
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS event_id TEXT;
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS authority_incarnation TEXT;
ALTER TABLE reviewer_assignments ADD COLUMN IF NOT EXISTS expected_work_item_revision BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS authority_instances_one_active
    ON authority_instances(authority_id) WHERE status='active';

-- Trusted Node admission owns these nullable bindings. Existing/unregistered
-- Attempts remain ineligible: no defaults or request-body backfill is safe.
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS observer_ref TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS observer_grant_ref TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS execution_command_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS execution_operation_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS execution_event_id TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS provider TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS source_baseline TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS source_commit TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS source_tree TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS candidate_ref TEXT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS execution_started_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS attempts_registered_execution_operation
    ON attempts(tenant_id,execution_operation_id)
    WHERE execution_operation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS attempts_registered_execution_event
    ON attempts(tenant_id,execution_event_id)
    WHERE execution_event_id IS NOT NULL;

-- A publication Effect binds the already reviewed candidate independently of
-- its resource path or source baseline. Old unbound Effects fail acceptance;
-- admission must derive this from the authorized readiness/source contract.
ALTER TABLE effects ADD COLUMN IF NOT EXISTS candidate_ref TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS operation_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS expected_sha256 TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS expected_size_bytes BIGINT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS intent_sha256 TEXT;

-- Both transition and Effect admission serialize on the parent WorkItem.
-- With READ COMMITTED, admission which wins this lock is visible to acceptance
-- enumeration. Admission which loses waits and then rejects after acceptance.
-- Gateways should explicitly acquire WorkItem BEFORE Effect row locks; this
-- trigger is an integrity barrier, not a substitute for that deadlock order.
CREATE OR REPLACE FUNCTION acs_effect_work_item_barrier() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    effect_tenant TEXT;
    effect_work_item TEXT;
    parent_state TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'registered effect history cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
        NEW.work_item_id IS DISTINCT FROM OLD.work_item_id OR
        NEW.effect_id IS DISTINCT FROM OLD.effect_id
    ) THEN
        RAISE EXCEPTION 'effect parent identity is immutable' USING ERRCODE = '23514';
    END IF;
    effect_tenant := NEW.tenant_id;
    effect_work_item := NEW.work_item_id;
    SELECT state INTO parent_state FROM work_items
      WHERE tenant_id = effect_tenant AND work_item_id = effect_work_item
      FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'effect parent work item is missing' USING ERRCODE = '23503';
    END IF;
    IF parent_state = 'accepted' THEN
        RAISE EXCEPTION 'accepted work item rejects effect mutation' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS acs_effect_work_item_barrier ON effects;
CREATE TRIGGER acs_effect_work_item_barrier
BEFORE INSERT OR UPDATE OR DELETE ON effects
FOR EACH ROW EXECUTE FUNCTION acs_effect_work_item_barrier();

-- Runtime 1.5 authenticated Effect registration and reconciliation.
-- Append to the Runtime schema; nullable adoption never invents old proofs.
ALTER TABLE effects ADD COLUMN IF NOT EXISTS completion_sha256 TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS completion_state TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS registered_readback JSONB;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS registered_by TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS registration_command_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS registration_operation_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS registration_event_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS reconciled_readback JSONB;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS reconciliation_command_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS reconciliation_operation_id TEXT;
ALTER TABLE effects ADD COLUMN IF NOT EXISTS reconciliation_event_id TEXT;

-- Formal registration seals identity and its first observation. Reconciliation
-- may update completion/status and its own audit columns, never these bindings.
-- Legacy rows with no registration command retain their existing migration path.
CREATE OR REPLACE FUNCTION acs_registered_effect_identity_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.registration_command_id IS NOT NULL AND (
        ROW(NEW.effect_id,NEW.tenant_id,NEW.work_item_id,NEW.resource_id,NEW.baseline_ref,
            NEW.lease_id,NEW.fencing_token,NEW.generation,NEW.grant_ref,NEW.candidate_ref,
            NEW.operation_id,NEW.readback_ref,NEW.expected_sha256,NEW.expected_size_bytes,NEW.intent_sha256,
            NEW.registered_readback,NEW.registered_by,NEW.registration_command_id,NEW.registration_operation_id)
        IS DISTINCT FROM
        ROW(OLD.effect_id,OLD.tenant_id,OLD.work_item_id,OLD.resource_id,OLD.baseline_ref,
            OLD.lease_id,OLD.fencing_token,OLD.generation,OLD.grant_ref,OLD.candidate_ref,
            OLD.operation_id,OLD.readback_ref,OLD.expected_sha256,OLD.expected_size_bytes,OLD.intent_sha256,
            OLD.registered_readback,OLD.registered_by,OLD.registration_command_id,OLD.registration_operation_id)
        OR (OLD.registration_event_id IS NOT NULL AND NEW.registration_event_id IS DISTINCT FROM OLD.registration_event_id)
    ) THEN
        RAISE EXCEPTION 'registered effect identity and original proof are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS acs_registered_effect_identity_guard ON effects;
CREATE TRIGGER acs_registered_effect_identity_guard BEFORE UPDATE ON effects
FOR EACH ROW EXECUTE FUNCTION acs_registered_effect_identity_guard();
