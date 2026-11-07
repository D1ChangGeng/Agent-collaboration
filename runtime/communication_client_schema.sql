-- Optional client-owned state inside the existing PostgreSQL Authority.
-- No message/conversation body copy: read frontiers and preferences are private
-- projections. Draft content is explicitly unsent, not Agent history.
CREATE TABLE IF NOT EXISTS communication_client_read_state (
    tenant_id TEXT NOT NULL CHECK(char_length(tenant_id) BETWEEN 1 AND 512),
    project_id TEXT NOT NULL CHECK(char_length(project_id) BETWEEN 1 AND 512),
    actor_ref TEXT NOT NULL CHECK(char_length(actor_ref) BETWEEN 1 AND 512),
    conversation_id TEXT NOT NULL CHECK(char_length(conversation_id) BETWEEN 1 AND 512),
    through_message_handle TEXT,
    through_sequence BIGINT NOT NULL DEFAULT 0 CHECK(through_sequence >= 0),
    unread_override BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,actor_ref,conversation_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CHECK((through_sequence=0 AND through_message_handle IS NULL) OR
          (through_sequence>0 AND through_message_handle IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS communication_client_preferences (
    tenant_id TEXT NOT NULL CHECK(char_length(tenant_id) BETWEEN 1 AND 512),
    project_id TEXT NOT NULL CHECK(char_length(project_id) BETWEEN 1 AND 512),
    actor_ref TEXT NOT NULL CHECK(char_length(actor_ref) BETWEEN 1 AND 512),
    conversation_id TEXT NOT NULL CHECK(char_length(conversation_id) BETWEEN 1 AND 512),
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    muted BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,actor_ref,conversation_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE IF NOT EXISTS communication_client_drafts (
    tenant_id TEXT NOT NULL CHECK(char_length(tenant_id) BETWEEN 1 AND 512),
    project_id TEXT NOT NULL CHECK(char_length(project_id) BETWEEN 1 AND 512),
    actor_ref TEXT NOT NULL CHECK(char_length(actor_ref) BETWEEN 1 AND 512),
    conversation_id TEXT NOT NULL CHECK(char_length(conversation_id) BETWEEN 1 AND 512),
    content TEXT NOT NULL CHECK(octet_length(content)<=262144),
    attachment_refs TEXT[] NOT NULL CHECK(cardinality(attachment_refs)<=8),
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,actor_ref,conversation_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CHECK(NOT deleted OR (content='' AND cardinality(attachment_refs)=0))
);
-- Per-operation retry receipts are separate from current state so a retry can
-- return its original result after unrelated later revisions, before CAS.
CREATE TABLE IF NOT EXISTS communication_client_write_keys (
    tenant_id TEXT NOT NULL CHECK(char_length(tenant_id) BETWEEN 1 AND 512),
    project_id TEXT NOT NULL CHECK(char_length(project_id) BETWEEN 1 AND 512),
    actor_ref TEXT NOT NULL CHECK(char_length(actor_ref) BETWEEN 1 AND 512),
    operation_kind TEXT NOT NULL CHECK(operation_kind IN ('read_state','preferences','draft.write','draft.delete')),
    client_request_id TEXT NOT NULL CHECK(char_length(client_request_id) BETWEEN 1 AND 512),
    canonical_hash TEXT NOT NULL CHECK(canonical_hash ~ '^[a-f0-9]{64}$'),
    result_json JSONB NOT NULL CHECK(jsonb_typeof(result_json)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,actor_ref,operation_kind,client_request_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
-- This singleton is an encryption key, not a signing/identity or message key.
-- Only explicit storage adoption creates it; startup reads never regenerate it.
CREATE TABLE IF NOT EXISTS communication_client_cursor_key (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    secret BYTEA NOT NULL CHECK(octet_length(secret)=32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
-- Technical read-model version only; original packet/author/reply data remain
-- in their owning tables. Updates occur in the source write transaction.
CREATE TABLE IF NOT EXISTS communication_delivery_versions (
    tenant_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,message_id),
    FOREIGN KEY(tenant_id,message_id) REFERENCES delivery_messages(tenant_id,message_id)
);
CREATE OR REPLACE FUNCTION acs_client_delivery_version_tick(p_tenant TEXT,p_message TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM delivery_messages WHERE tenant_id=p_tenant AND message_id=p_message
              AND packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1')) THEN
        INSERT INTO communication_delivery_versions(tenant_id,message_id,revision,updated_at)
        VALUES(p_tenant,p_message,1,clock_timestamp())
        ON CONFLICT(tenant_id,message_id) DO UPDATE
        SET revision=communication_delivery_versions.revision+1,updated_at=clock_timestamp();
    END IF;
END;
$$;
CREATE OR REPLACE FUNCTION acs_client_delivery_message_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN
        IF ROW(NEW.state,NEW.attempts,NEW.receipt_high_water,NEW.last_error,NEW.endpoint_id,NEW.binding_revision)
           IS NOT DISTINCT FROM
           ROW(OLD.state,OLD.attempts,OLD.receipt_high_water,OLD.last_error,OLD.endpoint_id,OLD.binding_revision) THEN
            RETURN NEW;
        END IF;
    END IF;
    PERFORM acs_client_delivery_version_tick(NEW.tenant_id,NEW.message_id);
    RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION acs_client_delivery_receipt_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM acs_client_delivery_version_tick(NEW.tenant_id,NEW.message_id);
    RETURN NEW;
END;
$$;
CREATE OR REPLACE FUNCTION acs_client_delivery_reply_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM acs_client_delivery_version_tick(NEW.tenant_id,NEW.request_id);
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS acs_client_delivery_message_version ON delivery_messages;
CREATE TRIGGER acs_client_delivery_message_version
AFTER INSERT OR UPDATE OF state,attempts,receipt_high_water,last_error,endpoint_id,binding_revision ON delivery_messages
FOR EACH ROW EXECUTE FUNCTION acs_client_delivery_message_version();
DROP TRIGGER IF EXISTS acs_client_delivery_receipt_version ON delivery_receipts;
CREATE TRIGGER acs_client_delivery_receipt_version AFTER INSERT ON delivery_receipts
FOR EACH ROW EXECUTE FUNCTION acs_client_delivery_receipt_version();
DROP TRIGGER IF EXISTS acs_client_delivery_reply_version ON communication_replies;
CREATE TRIGGER acs_client_delivery_reply_version AFTER INSERT ON communication_replies
FOR EACH ROW EXECUTE FUNCTION acs_client_delivery_reply_version();
INSERT INTO communication_delivery_versions(tenant_id,message_id,revision,updated_at)
SELECT tenant_id,message_id,1,clock_timestamp() FROM delivery_messages
WHERE packet_json->>'schema_version' IN ('acs-message/1','acs-notice/1')
ON CONFLICT(tenant_id,message_id) DO NOTHING;
-- A conservative project-wide Contact projection version. All contacts in the
-- namespace may be invalidated by one change; no list/read allocates versions.
-- Keep the counter outside individual endpoint/team rows so DELETE/recreate and
-- binding ABA cannot reset the revision observed by an authorized client.
CREATE TABLE IF NOT EXISTS communication_contact_versions (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK(revision >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id) ON DELETE CASCADE
);
CREATE OR REPLACE FUNCTION acs_client_contact_version_tick(p_tenant TEXT,p_project TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM collaboration_projects WHERE tenant_id=p_tenant AND project_id=p_project) THEN
        INSERT INTO communication_contact_versions(tenant_id,project_id,revision,updated_at)
        VALUES(p_tenant,p_project,1,clock_timestamp())
        ON CONFLICT(tenant_id,project_id) DO UPDATE
        SET revision=communication_contact_versions.revision+1,updated_at=clock_timestamp();
    END IF;
END;
$$;
CREATE OR REPLACE FUNCTION acs_client_contact_project_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_tenant TEXT; prior_project TEXT; next_tenant TEXT; next_project TEXT; selected RECORD;
BEGIN
    IF TG_OP='UPDATE' THEN
        IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NULL; END IF;
    END IF;
    IF TG_OP<>'INSERT' THEN
        prior_tenant:=OLD.tenant_id; prior_project:=OLD.project_id;
    END IF;
    IF TG_OP<>'DELETE' THEN
        next_tenant:=NEW.tenant_id; next_project:=NEW.project_id;
    END IF;
    FOR selected IN SELECT DISTINCT tenant_id,project_id FROM
        (VALUES(prior_tenant,prior_project),(next_tenant,next_project)) affected(tenant_id,project_id)
        WHERE tenant_id IS NOT NULL ORDER BY tenant_id,project_id
    LOOP
        PERFORM acs_client_contact_version_tick(selected.tenant_id,selected.project_id);
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE OR REPLACE FUNCTION acs_client_contact_slot_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_tenant TEXT; prior_slot TEXT; next_tenant TEXT; next_slot TEXT; selected RECORD;
BEGIN
    IF TG_OP='UPDATE' THEN
        IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NULL; END IF;
    END IF;
    IF TG_OP<>'INSERT' THEN
        prior_tenant:=OLD.tenant_id; prior_slot:=OLD.agent_slot_id;
    END IF;
    IF TG_OP<>'DELETE' THEN
        next_tenant:=NEW.tenant_id; next_slot:=NEW.agent_slot_id;
    END IF;
    -- Lock both ends of a rebind in a stable order so opposite rebinds cannot
    -- invert the additional contact-counter locks.
    FOR selected IN
        SELECT tenant_id,project_id FROM collaboration_memberships
        WHERE (tenant_id=prior_tenant AND agent_slot_id=prior_slot) OR (tenant_id=next_tenant AND agent_slot_id=next_slot)
        UNION SELECT tenant_id,project_id FROM collaboration_team_members
        WHERE (tenant_id=prior_tenant AND agent_slot_id=prior_slot) OR (tenant_id=next_tenant AND agent_slot_id=next_slot)
        ORDER BY tenant_id,project_id
    LOOP
        PERFORM acs_client_contact_version_tick(selected.tenant_id,selected.project_id);
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_client_contact_teams_version AFTER INSERT OR UPDATE OR DELETE ON collaboration_teams
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_project_version();
CREATE TRIGGER acs_client_contact_members_version AFTER INSERT OR UPDATE OR DELETE ON collaboration_team_members
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_project_version();
CREATE TRIGGER acs_client_contact_memberships_version AFTER INSERT OR UPDATE OR DELETE ON collaboration_memberships
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_project_version();
CREATE TRIGGER acs_client_contact_supervisors_version AFTER INSERT OR UPDATE OR DELETE ON communication_supervisors
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_project_version();
CREATE TRIGGER acs_client_contact_endpoints_version AFTER INSERT OR UPDATE OR DELETE ON delivery_endpoints
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_slot_version();
CREATE TRIGGER acs_client_contact_slots_version AFTER INSERT OR UPDATE OR DELETE ON agent_slots
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_slot_version();
-- Explicit storage adoption seeds current projects. An actually admitted new
-- project receives its initial row in that same source transaction as well.
CREATE TRIGGER acs_client_contact_projects_version AFTER INSERT ON collaboration_projects
FOR EACH ROW EXECUTE FUNCTION acs_client_contact_project_version();
INSERT INTO communication_contact_versions(tenant_id,project_id,revision,updated_at)
SELECT tenant_id,project_id,1,clock_timestamp() FROM collaboration_projects
ON CONFLICT(tenant_id,project_id) DO NOTHING;
