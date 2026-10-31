-- Runtime 1.12: delegated authorization is checked at every Domain boundary.
CREATE TABLE IF NOT EXISTS grant_delegations (
    grant_ref TEXT PRIMARY KEY REFERENCES grants(grant_ref),
    parent_grant_ref TEXT NOT NULL REFERENCES grants(grant_ref),
    tenant_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    parent_policy_digest TEXT NOT NULL CHECK(length(parent_policy_digest)=64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK(grant_ref <> parent_grant_ref)
);
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS work_item_revisions (
    tenant_id TEXT NOT NULL,work_item_id TEXT NOT NULL REFERENCES work_items(work_item_id),
    revision BIGINT NOT NULL,definition JSONB NOT NULL,source_baseline TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,command_id TEXT NOT NULL,reason TEXT NOT NULL,
    PRIMARY KEY(tenant_id,work_item_id,revision)
);
ALTER TABLE domain_events ADD COLUMN IF NOT EXISTS writer_xid xid8 NOT NULL DEFAULT pg_current_xact_id();
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
