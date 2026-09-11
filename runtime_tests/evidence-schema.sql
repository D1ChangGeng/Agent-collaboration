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
