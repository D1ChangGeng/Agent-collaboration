-- Optional notice metadata/private seen state. Never copies a private message.
CREATE TABLE communication_client_notice_versions (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, message_id TEXT NOT NULL, recipient TEXT NOT NULL,
    notice_ref TEXT NOT NULL DEFAULT ('notice-'||replace(gen_random_uuid()::text,'-','')),
    revision BIGINT NOT NULL CHECK(revision>=1), created_at TIMESTAMPTZ,
    PRIMARY KEY(tenant_id,project_id,message_id,recipient),
    UNIQUE(tenant_id,project_id,notice_ref),
    FOREIGN KEY(tenant_id,project_id,message_id,recipient)
      REFERENCES communication_notices(tenant_id,project_id,message_id,recipient) ON DELETE CASCADE
);
CREATE TABLE communication_client_notice_seen (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, actor_ref TEXT NOT NULL,
    message_id TEXT NOT NULL, recipient TEXT NOT NULL, seen BOOLEAN NOT NULL,
    revision BIGINT NOT NULL CHECK(revision>=1), updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,actor_ref,message_id,recipient),
    FOREIGN KEY(tenant_id,project_id,message_id,recipient)
      REFERENCES communication_client_notice_versions(tenant_id,project_id,message_id,recipient) ON DELETE CASCADE
);
CREATE TABLE communication_client_notice_write_keys (
    tenant_id TEXT NOT NULL, actor_ref TEXT NOT NULL, client_request_id TEXT NOT NULL,
    canonical_hash TEXT NOT NULL CHECK(canonical_hash ~ '^[a-f0-9]{64}$'),
    result_json JSONB NOT NULL CHECK(jsonb_typeof(result_json)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,actor_ref,client_request_id)
);
CREATE INDEX communication_client_notice_page ON communication_notices(tenant_id,project_id,recipient,sequence);
CREATE FUNCTION acs_client_notice_source_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        INSERT INTO communication_client_notice_versions(tenant_id,project_id,message_id,recipient,revision,created_at)
        VALUES(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient,1,clock_timestamp());
    ELSIF ROW(NEW.state,NEW.code) IS DISTINCT FROM ROW(OLD.state,OLD.code) THEN
        UPDATE communication_client_notice_versions SET revision=revision+1
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND message_id=NEW.message_id AND recipient=NEW.recipient;
    END IF;
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_client_notice_route_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' OR NEW IS DISTINCT FROM OLD THEN
        UPDATE communication_client_notice_versions SET revision=revision+1
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND message_id=NEW.message_id AND recipient=NEW.recipient;
    END IF;
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_client_notice_delivery_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' OR NEW.revision IS DISTINCT FROM OLD.revision THEN
        UPDATE communication_client_notice_versions v SET revision=v.revision+1
        FROM communication_notice_routes r WHERE r.tenant_id=NEW.tenant_id AND r.delivery_message_id=NEW.message_id
        AND (v.tenant_id,v.project_id,v.message_id,v.recipient)=(r.tenant_id,r.project_id,r.message_id,r.recipient);
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_client_notice_source_version AFTER INSERT OR UPDATE OF state,code ON communication_notices
FOR EACH ROW EXECUTE FUNCTION acs_client_notice_source_version();
CREATE TRIGGER acs_client_notice_route_version AFTER INSERT OR UPDATE ON communication_notice_routes
FOR EACH ROW EXECUTE FUNCTION acs_client_notice_route_version();
CREATE TRIGGER acs_client_notice_delivery_version AFTER INSERT OR UPDATE ON communication_delivery_versions
FOR EACH ROW EXECUTE FUNCTION acs_client_notice_delivery_version();
-- No historical timestamp exists. Adoption must not fabricate its creation time.
INSERT INTO communication_client_notice_versions(tenant_id,project_id,message_id,recipient,revision,created_at)
SELECT tenant_id,project_id,message_id,recipient,1,NULL FROM communication_notices;
