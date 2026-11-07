-- Persist only typed receiver metadata, never message/draft/transcript content.
-- The resource counter survives changes to its endpoint epoch/Node/Native binding.
CREATE FUNCTION acs_receiver_observation_key(value TEXT) RETURNS BYTEA
LANGUAGE SQL IMMUTABLE STRICT AS $$ SELECT pg_catalog.sha256(pg_catalog.convert_to(value,'UTF8')); $$;
CREATE TABLE communication_receiver_observations (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    receiver_id TEXT NOT NULL,
    receiver_key BYTEA GENERATED ALWAYS AS (acs_receiver_observation_key(receiver_id)) STORED NOT NULL,
    selection_json JSONB NOT NULL,
    selection_digest TEXT NOT NULL,
    snapshot_json JSONB NOT NULL,
    snapshot_digest TEXT NOT NULL,
    resource_revision BIGINT NOT NULL,
    semantic_digest TEXT NOT NULL,
    capability_digest TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,receiver_key),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(tenant_id,receiver_id) REFERENCES delivery_endpoints(tenant_id,endpoint_id),
    CONSTRAINT receiver_observation_references CHECK (char_length(tenant_id)>=1 AND char_length(tenant_id)<=512 AND char_length(project_id)>=1 AND char_length(project_id)<=512 AND char_length(receiver_id)>=1 AND char_length(receiver_id)<=512),
    CONSTRAINT receiver_observation_hashes CHECK (selection_digest ~ '^[0-9a-f]{64}$' AND snapshot_digest ~ '^[0-9a-f]{64}$' AND semantic_digest ~ '^[0-9a-f]{64}$' AND capability_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT receiver_observation_key_size CHECK (octet_length(receiver_key)=32),
    CONSTRAINT receiver_observation_revision CHECK (resource_revision >= 1),
    CONSTRAINT receiver_observation_objects CHECK (jsonb_typeof(selection_json)='object' AND jsonb_typeof(snapshot_json)='object'),
    CONSTRAINT receiver_observation_bounds CHECK (octet_length(selection_json::text)<=16384 AND octet_length(snapshot_json::text)<=1048576),
    CONSTRAINT receiver_observation_subject CHECK (selection_json->>'endpoint_id'=receiver_id AND snapshot_json->>'receiver_id'=receiver_id AND jsonb_typeof(snapshot_json->'revision')='number' AND (snapshot_json->>'revision')::bigint=resource_revision)
);
