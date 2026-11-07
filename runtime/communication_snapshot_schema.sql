-- Optional short-lived metadata cache, independently adopted from Authority data.
-- Source messages, drafts and Native transcripts never live in these relations.
CREATE TABLE communication_snapshot_scopes (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    generation BIGINT NOT NULL DEFAULT 0 CHECK(generation>=0),
    PRIMARY KEY(tenant_id,project_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id) ON DELETE CASCADE
);
CREATE TABLE communication_snapshots (
    snapshot_ref TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    viewer_key TEXT NOT NULL,
    auth_revision TEXT NOT NULL,
    filter_digest TEXT NOT NULL,
    high_water BIGINT NOT NULL,
    projection_json JSONB NOT NULL,
    header_digest TEXT NOT NULL,
    contacts_count INTEGER NOT NULL,
    conversations_count INTEGER NOT NULL,
    receivers_count INTEGER NOT NULL,
    total_items INTEGER NOT NULL,
    total_bytes BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE(tenant_id,project_id,snapshot_ref),
    FOREIGN KEY(tenant_id,project_id) REFERENCES communication_snapshot_scopes(tenant_id,project_id) ON DELETE CASCADE,
    CONSTRAINT snapshot_reference_format CHECK(snapshot_ref ~ '^snapshot-[A-Za-z0-9_-]{32}$'),
    CONSTRAINT snapshot_identity_bounds CHECK(char_length(tenant_id) BETWEEN 1 AND 512 AND char_length(project_id) BETWEEN 1 AND 512
        AND char_length(viewer_key) BETWEEN 1 AND 512 AND char_length(auth_revision) BETWEEN 1 AND 512),
    CONSTRAINT snapshot_hash_format CHECK(filter_digest ~ '^[a-f0-9]{64}$' AND header_digest ~ '^[a-f0-9]{64}$'),
    CONSTRAINT snapshot_metadata_object CHECK(jsonb_typeof(projection_json)='object'),
    CONSTRAINT snapshot_size_bounds CHECK(high_water>=0 AND contacts_count>=0 AND conversations_count>=0 AND receivers_count>=0
        AND total_items=contacts_count+conversations_count+receivers_count AND total_items<=50000 AND total_bytes BETWEEN 0 AND 67108864),
    CONSTRAINT snapshot_ttl_bounds CHECK(expires_at>created_at AND expires_at<=created_at+interval '300 seconds')
);
CREATE INDEX communication_snapshots_expiry ON communication_snapshots(expires_at,snapshot_ref);
CREATE INDEX communication_snapshots_owner ON communication_snapshots(tenant_id,project_id,viewer_key);
CREATE TABLE communication_snapshot_items (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    snapshot_ref TEXT NOT NULL,
    resource_family TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    resource_json JSONB NOT NULL,
    resource_digest TEXT NOT NULL,
    PRIMARY KEY(snapshot_ref,resource_family,item_index),
    FOREIGN KEY(tenant_id,project_id,snapshot_ref) REFERENCES communication_snapshots(tenant_id,project_id,snapshot_ref) ON DELETE CASCADE,
    CONSTRAINT snapshot_family_bounds CHECK(resource_family IN ('contacts','conversations','receivers') AND item_index BETWEEN 0 AND 49999),
    CONSTRAINT snapshot_item_object CHECK(jsonb_typeof(resource_json)='object'),
    CONSTRAINT snapshot_item_hash CHECK(resource_digest ~ '^[a-f0-9]{64}$')
);
CREATE FUNCTION acs_communication_snapshot_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable_communication_snapshot';
END;
$$;
CREATE TRIGGER acs_communication_snapshot_header_immutable BEFORE UPDATE ON communication_snapshots
FOR EACH ROW EXECUTE FUNCTION acs_communication_snapshot_immutable();
CREATE TRIGGER acs_communication_snapshot_item_immutable BEFORE UPDATE ON communication_snapshot_items
FOR EACH ROW EXECUTE FUNCTION acs_communication_snapshot_immutable();
INSERT INTO communication_snapshot_scopes(tenant_id,project_id)
SELECT tenant_id,project_id FROM collaboration_projects;
