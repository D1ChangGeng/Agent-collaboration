-- Native links retain metadata/provenance only. No Host permissions or transcript.
-- Hash physical keys; full Unicode identities remain authoritative and checked.
CREATE FUNCTION acs_native_link_key(value TEXT) RETURNS BYTEA LANGUAGE SQL IMMUTABLE STRICT
AS $$ SELECT pg_catalog.sha256(pg_catalog.convert_to(value,'UTF8')); $$;
CREATE TABLE communication_native_links (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    link_id TEXT NOT NULL, address TEXT NOT NULL, receiver_ref TEXT NOT NULL,
    tenant_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(tenant_id)) STORED NOT NULL,
    project_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(project_id)) STORED NOT NULL,
    scope_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(scope_id)) STORED NOT NULL,
    link_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(link_id)) STORED NOT NULL,
    revision BIGINT NOT NULL, link_json JSONB NOT NULL, link_digest TEXT NOT NULL,
    proof_json JSONB NOT NULL, proof_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(tenant_key,project_key,scope_key,link_key),
    UNIQUE(tenant_key,project_key,link_key),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(scope_id) REFERENCES scopes(scope_id),
    FOREIGN KEY(tenant_id,receiver_ref) REFERENCES delivery_endpoints(tenant_id,endpoint_id),
    CONSTRAINT native_link_ids CHECK(char_length(tenant_id)>=1 AND char_length(tenant_id)<=512 AND char_length(project_id)>=1 AND char_length(project_id)<=512 AND char_length(scope_id)>=1 AND char_length(scope_id)<=512 AND char_length(link_id)>=1 AND char_length(link_id)<=512 AND char_length(address)>=1 AND char_length(address)<=512 AND char_length(receiver_ref)>=1 AND char_length(receiver_ref)<=512),
    CONSTRAINT native_link_hashes CHECK(link_digest ~ '^[0-9a-f]{64}$' AND proof_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT native_link_keys CHECK(octet_length(tenant_key)=32 AND octet_length(project_key)=32 AND octet_length(scope_key)=32 AND octet_length(link_key)=32),
    CONSTRAINT native_link_revision CHECK(revision>=1 AND updated_at>=created_at),
    CONSTRAINT native_link_metadata CHECK(jsonb_typeof(link_json)='object' AND jsonb_typeof(proof_json)='object' AND octet_length(link_json::text)<=262144 AND octet_length(proof_json::text)<=262144),
    CONSTRAINT native_link_subject CHECK(link_json->>'link_id'=link_id AND link_json->>'project_id'=project_id AND link_json->>'address'=address AND link_json->>'receiver_ref'=receiver_ref AND jsonb_typeof(link_json->'revision')='number' AND (link_json->>'revision')::bigint=revision)
);
CREATE TABLE communication_native_link_history (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    link_id TEXT NOT NULL, address TEXT NOT NULL, receiver_ref TEXT NOT NULL,
    tenant_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(tenant_id)) STORED NOT NULL,
    project_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(project_id)) STORED NOT NULL,
    scope_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(scope_id)) STORED NOT NULL,
    link_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(link_id)) STORED NOT NULL,
    revision BIGINT NOT NULL, link_json JSONB NOT NULL, link_digest TEXT NOT NULL,
    proof_json JSONB NOT NULL, proof_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(tenant_key,project_key,scope_key,link_key,revision),
    FOREIGN KEY(tenant_key,project_key,scope_key,link_key) REFERENCES communication_native_links(tenant_key,project_key,scope_key,link_key),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    FOREIGN KEY(scope_id) REFERENCES scopes(scope_id),
    FOREIGN KEY(tenant_id,receiver_ref) REFERENCES delivery_endpoints(tenant_id,endpoint_id),
    CONSTRAINT native_link_history_ids CHECK(char_length(tenant_id)>=1 AND char_length(tenant_id)<=512 AND char_length(project_id)>=1 AND char_length(project_id)<=512 AND char_length(scope_id)>=1 AND char_length(scope_id)<=512 AND char_length(link_id)>=1 AND char_length(link_id)<=512 AND char_length(address)>=1 AND char_length(address)<=512 AND char_length(receiver_ref)>=1 AND char_length(receiver_ref)<=512),
    CONSTRAINT native_link_history_hashes CHECK(link_digest ~ '^[0-9a-f]{64}$' AND proof_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT native_link_history_revision CHECK(revision>=1 AND updated_at>=created_at),
    CONSTRAINT native_link_history_metadata CHECK(jsonb_typeof(link_json)='object' AND jsonb_typeof(proof_json)='object' AND octet_length(link_json::text)<=262144 AND octet_length(proof_json::text)<=262144),
    CONSTRAINT native_link_history_subject CHECK(link_json->>'link_id'=link_id AND link_json->>'project_id'=project_id AND link_json->>'address'=address AND link_json->>'receiver_ref'=receiver_ref AND jsonb_typeof(link_json->'revision')='number' AND (link_json->>'revision')::bigint=revision)
);
CREATE TABLE communication_native_link_requests (
    request_context TEXT NOT NULL, request_namespace TEXT NOT NULL,
    request_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(request_context)) STORED NOT NULL PRIMARY KEY,
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, scope_id TEXT NOT NULL, link_id TEXT NOT NULL,
    viewer_key TEXT NOT NULL, authority_id TEXT NOT NULL, authority_incarnation TEXT NOT NULL,
    tenant_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(tenant_id)) STORED NOT NULL,
    project_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(project_id)) STORED NOT NULL,
    scope_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(scope_id)) STORED NOT NULL,
    link_key BYTEA GENERATED ALWAYS AS (acs_native_link_key(link_id)) STORED NOT NULL,
    revision BIGINT NOT NULL, input_json JSONB NOT NULL, input_digest TEXT NOT NULL,
    result_json JSONB NOT NULL, result_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY(tenant_key,project_key,scope_key,link_key,revision) REFERENCES communication_native_link_history(tenant_key,project_key,scope_key,link_key,revision),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CONSTRAINT native_link_request_ids CHECK(char_length(tenant_id)>=1 AND char_length(tenant_id)<=512 AND char_length(project_id)>=1 AND char_length(project_id)<=512 AND char_length(scope_id)>=1 AND char_length(scope_id)<=512 AND char_length(link_id)>=1 AND char_length(link_id)<=512 AND viewer_key ~ '^viewer-[0-9a-f]{64}$' AND char_length(authority_id)>=1 AND char_length(authority_id)<=512 AND char_length(authority_incarnation)>=1 AND char_length(authority_incarnation)<=512),
    CONSTRAINT native_link_request_context CHECK(char_length(request_namespace)>=1 AND char_length(request_namespace)<=4096 AND octet_length(request_context)<=131072 AND octet_length(request_key)=32),
    CONSTRAINT native_link_request_hashes CHECK(input_digest ~ '^[0-9a-f]{64}$' AND result_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT native_link_request_revision CHECK(revision>=1),
    CONSTRAINT native_link_request_metadata CHECK(jsonb_typeof(input_json)='object' AND jsonb_typeof(result_json)='object' AND octet_length(input_json::text)<=262144 AND octet_length(result_json::text)<=262144)
);
CREATE FUNCTION acs_native_link_current_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'native_link_metadata_is_retained'; END IF;
    IF ROW(NEW.tenant_id,NEW.project_id,NEW.scope_id,NEW.link_id,NEW.address,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.tenant_id,OLD.project_id,OLD.scope_id,OLD.link_id,OLD.address,OLD.created_at)
       OR NEW.revision<>OLD.revision+1 OR NEW.updated_at<OLD.updated_at THEN
        RAISE EXCEPTION 'native_link_identity_or_revision_conflict';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER acs_native_link_current_guard BEFORE UPDATE OR DELETE ON communication_native_links
FOR EACH ROW EXECUTE FUNCTION acs_native_link_current_guard();
CREATE FUNCTION acs_native_link_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'native_link_history_is_immutable';
END;
$$;
CREATE TRIGGER acs_native_link_history_guard BEFORE UPDATE OR DELETE ON communication_native_link_history
FOR EACH ROW EXECUTE FUNCTION acs_native_link_history_guard();
CREATE TRIGGER acs_native_link_request_guard BEFORE UPDATE OR DELETE ON communication_native_link_requests
FOR EACH ROW EXECUTE FUNCTION acs_native_link_history_guard();
