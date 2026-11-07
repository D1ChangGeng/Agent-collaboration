-- Explicit uploads are private to a stable viewer until an actual message pins
-- them. BYTEA chunks are temporary; accepted CAS content is never deleted here.
CREATE FUNCTION acs_attachment_request_hash(value TEXT) RETURNS BYTEA LANGUAGE SQL IMMUTABLE STRICT
AS $$ SELECT pg_catalog.sha256(pg_catalog.convert_to(value,'UTF8')); $$;
CREATE TABLE communication_attachments (
    attachment_id TEXT PRIMARY KEY CHECK(attachment_id ~ '^attachment-[0-9a-f]{32}$'),
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, viewer_key TEXT NOT NULL,
    owner_address TEXT NOT NULL, scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
    name TEXT NOT NULL, media_type TEXT NOT NULL, declared_bytes BIGINT NOT NULL,
    declared_sha256 TEXT NOT NULL, declaration_digest TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'reserved', revision BIGINT NOT NULL DEFAULT 1,
    generation BIGINT NOT NULL DEFAULT 0, lease_token TEXT, lease_expires_at TIMESTAMPTZ,
    chunk_bytes INTEGER NOT NULL, received_bytes BIGINT NOT NULL DEFAULT 0,
    artifact_json JSONB, artifact_digest TEXT, pinned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), expires_at TIMESTAMPTZ,
    UNIQUE(tenant_id,project_id,attachment_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CONSTRAINT attachment_identity CHECK(char_length(tenant_id) BETWEEN 1 AND 512 AND char_length(project_id) BETWEEN 1 AND 512 AND viewer_key ~ '^viewer-[0-9a-f]{64}$' AND char_length(owner_address) BETWEEN 1 AND 512 AND char_length(scope_id) BETWEEN 1 AND 256),
    CONSTRAINT attachment_declaration CHECK(char_length(name) BETWEEN 1 AND 255 AND char_length(media_type) BETWEEN 1 AND 256 AND declared_bytes BETWEEN 1 AND 268435456 AND declared_sha256 ~ '^[0-9a-f]{64}$' AND declaration_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT attachment_state CHECK(state IN ('reserved','uploaded','ready','rejected','expired') AND revision>=1 AND generation>=0 AND received_bytes BETWEEN 0 AND declared_bytes AND chunk_bytes BETWEEN 1 AND 1048576),
    CONSTRAINT attachment_lease CHECK((lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND generation>=1)),
    CONSTRAINT attachment_uploaded CHECK(state NOT IN ('uploaded','ready') OR received_bytes=declared_bytes),
    CONSTRAINT attachment_artifact CHECK((artifact_json IS NULL AND artifact_digest IS NULL) OR (jsonb_typeof(artifact_json)='object' AND artifact_digest ~ '^[0-9a-f]{64}$')),
    CONSTRAINT attachment_ready CHECK(state<>'ready' OR artifact_json IS NOT NULL),
    CONSTRAINT attachment_pinned CHECK(NOT pinned OR (state='ready' AND expires_at IS NULL)),
    CONSTRAINT attachment_expiry CHECK(pinned OR expires_at IS NOT NULL)
);
CREATE INDEX communication_attachment_owner ON communication_attachments(tenant_id,project_id,viewer_key);
CREATE INDEX communication_attachment_expiry ON communication_attachments(expires_at,attachment_id) WHERE NOT pinned AND state<>'expired';
CREATE TABLE communication_attachment_chunks (
    attachment_id TEXT NOT NULL REFERENCES communication_attachments(attachment_id),
    generation BIGINT NOT NULL CHECK(generation>=1), chunk_offset BIGINT NOT NULL CHECK(chunk_offset>=0),
    data BYTEA NOT NULL CHECK(octet_length(data) BETWEEN 1 AND 1048576),
    data_hash BYTEA GENERATED ALWAYS AS (pg_catalog.sha256(data)) STORED NOT NULL,
    resulting_revision BIGINT NOT NULL CHECK(resulting_revision>=1),
    PRIMARY KEY(attachment_id,generation,chunk_offset)
);
CREATE TABLE communication_attachment_requests (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, viewer_key TEXT NOT NULL,
    request_namespace TEXT NOT NULL CHECK(char_length(request_namespace) BETWEEN 1 AND 512),
    request_hash BYTEA GENERATED ALWAYS AS (acs_attachment_request_hash(request_namespace)) STORED NOT NULL,
    operation_kind TEXT NOT NULL CHECK(operation_kind ~ '^[a-z][a-z0-9._-]{0,63}$'), input_digest TEXT NOT NULL CHECK(input_digest ~ '^[0-9a-f]{64}$'),
    result_json JSONB NOT NULL CHECK(jsonb_typeof(result_json)='object'), result_digest TEXT NOT NULL CHECK(result_digest ~ '^[0-9a-f]{64}$'),
    attachment_id TEXT NOT NULL REFERENCES communication_attachments(attachment_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,viewer_key,request_hash),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE communication_message_attachments (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, message_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position>=0),
    PRIMARY KEY(tenant_id,project_id,message_id,attachment_id),
    UNIQUE(tenant_id,project_id,message_id,position),
    FOREIGN KEY(tenant_id,project_id,message_id) REFERENCES communication_messages(tenant_id,project_id,message_id),
    FOREIGN KEY(tenant_id,project_id,attachment_id) REFERENCES communication_attachments(tenant_id,project_id,attachment_id)
);
CREATE FUNCTION acs_attachment_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.attachment_id,NEW.tenant_id,NEW.project_id,NEW.viewer_key,NEW.owner_address,NEW.scope_id,NEW.name,NEW.media_type,NEW.declared_bytes,NEW.declared_sha256,NEW.declaration_digest,NEW.chunk_bytes,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.attachment_id,OLD.tenant_id,OLD.project_id,OLD.viewer_key,OLD.owner_address,OLD.scope_id,OLD.name,OLD.media_type,OLD.declared_bytes,OLD.declared_sha256,OLD.declaration_digest,OLD.chunk_bytes,OLD.created_at)
       OR (OLD.artifact_json IS NOT NULL AND ROW(NEW.artifact_json,NEW.artifact_digest) IS DISTINCT FROM ROW(OLD.artifact_json,OLD.artifact_digest))
       OR (OLD.pinned AND (NOT NEW.pinned OR NEW.state<>'ready' OR NEW.expires_at IS NOT NULL))
       OR NEW.revision<>OLD.revision+1 THEN
        RAISE EXCEPTION 'attachment_immutable_or_revision_conflict';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER acs_attachment_immutable BEFORE UPDATE ON communication_attachments
FOR EACH ROW EXECUTE FUNCTION acs_attachment_immutable();
