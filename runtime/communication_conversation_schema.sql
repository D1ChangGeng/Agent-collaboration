-- Permanent directed query-view versions; Authority messages/state stay primary.
-- Address hashes keep the physical key bounded for legal Unicode Slot handles.
CREATE FUNCTION acs_conversation_address_hash(value TEXT) RETURNS BYTEA
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $$
SELECT sha256(convert_to(value,'UTF8'));
$$;
CREATE TABLE communication_conversation_versions (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    viewer_address TEXT NOT NULL,
    peer_address TEXT NOT NULL,
    viewer_hash BYTEA GENERATED ALWAYS AS (acs_conversation_address_hash(viewer_address)) STORED NOT NULL,
    peer_hash BYTEA GENERATED ALWAYS AS (acs_conversation_address_hash(peer_address)) STORED NOT NULL,
    actor_ref TEXT,
    message_count BIGINT NOT NULL DEFAULT 0,
    read_revision BIGINT NOT NULL DEFAULT 0,
    preferences_revision BIGINT NOT NULL DEFAULT 0,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,viewer_hash,peer_hash),
    UNIQUE(tenant_id,project_id,conversation_id,actor_ref),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id) ON DELETE CASCADE,
    CONSTRAINT conversation_version_identity CHECK(char_length(tenant_id) BETWEEN 1 AND 512 AND char_length(project_id) BETWEEN 1 AND 512
        AND char_length(conversation_id) BETWEEN 1 AND 512 AND char_length(viewer_address) BETWEEN 1 AND 512
        AND char_length(peer_address) BETWEEN 1 AND 512 AND (actor_ref IS NULL OR char_length(actor_ref) BETWEEN 1 AND 512)),
    CONSTRAINT conversation_version_nonnegative CHECK(message_count>=0 AND read_revision>=0 AND preferences_revision>=0 AND revision>=0),
    CONSTRAINT conversation_version_hashes CHECK(octet_length(viewer_hash)=32 AND octet_length(peer_hash)=32)
);
CREATE FUNCTION acs_conversation_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.tenant_id,NEW.project_id,NEW.conversation_id,NEW.viewer_address,NEW.peer_address)
       IS DISTINCT FROM ROW(OLD.tenant_id,OLD.project_id,OLD.conversation_id,OLD.viewer_address,OLD.peer_address)
       OR (OLD.actor_ref IS NOT NULL AND NEW.actor_ref IS DISTINCT FROM OLD.actor_ref)
       OR NEW.message_count<OLD.message_count OR NEW.read_revision<OLD.read_revision
       OR NEW.preferences_revision<OLD.preferences_revision OR NEW.revision<OLD.revision THEN
        RAISE EXCEPTION 'conversation_version_identity_or_counter_reset';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER acs_conversation_version_guard BEFORE UPDATE ON communication_conversation_versions
FOR EACH ROW EXECUTE FUNCTION acs_conversation_identity_guard();
CREATE FUNCTION acs_conversation_refresh(p_tenant TEXT,p_project TEXT,p_viewer TEXT,p_peer TEXT,
    p_actor TEXT,p_force BOOLEAN,p_message_delta BOOLEAN) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE prior communication_conversation_versions%ROWTYPE; chosen_actor TEXT;
    actual_messages BIGINT; actual_read BIGINT:=0; actual_preferences BIGINT:=0;
    next_messages BIGINT; next_read BIGINT; next_preferences BIGINT; next_revision BIGINT;
BEGIN
    SELECT * INTO prior FROM communication_conversation_versions WHERE tenant_id=p_tenant AND project_id=p_project
      AND viewer_hash=acs_conversation_address_hash(p_viewer) AND peer_hash=acs_conversation_address_hash(p_peer) FOR UPDATE;
    IF NOT FOUND OR prior.viewer_address<>p_viewer OR prior.peer_address<>p_peer THEN
        RAISE EXCEPTION 'conversation_view_mapping_missing_or_collision';
    END IF;
    IF p_actor IS NOT NULL AND prior.actor_ref IS NOT NULL AND prior.actor_ref<>p_actor THEN
        RAISE EXCEPTION 'conversation_viewer_actor_conflict';
    END IF;
    chosen_actor:=COALESCE(prior.actor_ref,p_actor);
    -- Source reads are MVCC only. A source writer holding its private cell may
    -- wait on our counter, but this getter never waits on that private cell.
    SELECT count(*) INTO actual_messages FROM communication_messages WHERE tenant_id=p_tenant AND project_id=p_project
      AND ((sender=p_viewer AND recipient=p_peer) OR (sender=p_peer AND recipient=p_viewer));
    IF chosen_actor IS NOT NULL THEN
        SELECT COALESCE((SELECT revision FROM communication_client_read_state WHERE tenant_id=p_tenant AND project_id=p_project
          AND actor_ref=chosen_actor AND conversation_id=prior.conversation_id),0) INTO actual_read;
        SELECT COALESCE((SELECT revision FROM communication_client_preferences WHERE tenant_id=p_tenant AND project_id=p_project
          AND actor_ref=chosen_actor AND conversation_id=prior.conversation_id),0) INTO actual_preferences;
    END IF;
    next_messages:=GREATEST(prior.message_count+CASE WHEN p_message_delta THEN 1 ELSE 0 END,actual_messages);
    next_read:=GREATEST(prior.read_revision,actual_read);
    next_preferences:=GREATEST(prior.preferences_revision,actual_preferences);
    next_revision:=prior.revision;
    IF p_force OR ROW(next_messages,next_read,next_preferences) IS DISTINCT FROM
      ROW(prior.message_count,prior.read_revision,prior.preferences_revision) THEN
        next_revision:=GREATEST(prior.revision+1,next_messages+next_read+next_preferences);
    END IF;
    IF chosen_actor IS DISTINCT FROM prior.actor_ref OR next_revision<>prior.revision THEN
        UPDATE communication_conversation_versions SET actor_ref=chosen_actor,message_count=next_messages,
          read_revision=next_read,preferences_revision=next_preferences,revision=next_revision,updated_at=clock_timestamp()
          WHERE tenant_id=p_tenant AND project_id=p_project AND viewer_hash=prior.viewer_hash AND peer_hash=prior.peer_hash;
    END IF;
    RETURN next_revision;
END;
$$;
CREATE FUNCTION acs_conversation_message_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mapped RECORD;
BEGIN
    FOR mapped IN SELECT viewer_address,peer_address FROM communication_conversation_versions
      WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
      AND ((viewer_hash=acs_conversation_address_hash(NEW.sender) AND peer_hash=acs_conversation_address_hash(NEW.recipient)
            AND viewer_address=NEW.sender AND peer_address=NEW.recipient)
        OR (viewer_hash=acs_conversation_address_hash(NEW.recipient) AND peer_hash=acs_conversation_address_hash(NEW.sender)
            AND viewer_address=NEW.recipient AND peer_address=NEW.sender))
      ORDER BY viewer_hash,peer_hash
    LOOP
        PERFORM acs_conversation_refresh(NEW.tenant_id,NEW.project_id,mapped.viewer_address,mapped.peer_address,NULL,TRUE,TRUE);
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_conversation_private_refresh(p_tenant TEXT,p_project TEXT,p_conversation TEXT,p_actor TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE prepared JSONB; configured TEXT; mapped RECORD; found_prepared BOOLEAN:=FALSE;
BEGIN
    configured:=current_setting('acs.conversation_write',TRUE);
    IF NULLIF(configured,'') IS NOT NULL THEN
        prepared:=configured::jsonb;
        IF (prepared->>'tenant_id',prepared->>'project_id',prepared->>'conversation_id',prepared->>'actor_ref')=
           (p_tenant,p_project,p_conversation,p_actor) THEN
            PERFORM acs_conversation_refresh(p_tenant,p_project,prepared->>'viewer_address',prepared->>'peer_address',p_actor,TRUE,FALSE);
            found_prepared:=TRUE;
        END IF;
    END IF;
    IF NOT found_prepared THEN
        -- A direct internal helper with no prepared viewer may update an
        -- already-bound actor, but cannot guess ownership for a NULL map.
        FOR mapped IN SELECT viewer_address,peer_address FROM communication_conversation_versions
          WHERE tenant_id=p_tenant AND project_id=p_project AND conversation_id=p_conversation AND actor_ref=p_actor
          ORDER BY viewer_hash,peer_hash
        LOOP
            PERFORM acs_conversation_refresh(p_tenant,p_project,mapped.viewer_address,mapped.peer_address,p_actor,TRUE,FALSE);
        END LOOP;
    END IF;
END;
$$;
CREATE FUNCTION acs_conversation_private_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN
        IF TG_TABLE_NAME='communication_client_read_state' THEN
            IF ROW(NEW.tenant_id,NEW.project_id,NEW.actor_ref,NEW.conversation_id,NEW.through_message_handle,NEW.through_sequence,NEW.unread_override,NEW.revision)
              IS NOT DISTINCT FROM ROW(OLD.tenant_id,OLD.project_id,OLD.actor_ref,OLD.conversation_id,OLD.through_message_handle,OLD.through_sequence,OLD.unread_override,OLD.revision) THEN RETURN NULL; END IF;
        ELSE
            IF ROW(NEW.tenant_id,NEW.project_id,NEW.actor_ref,NEW.conversation_id,NEW.archived,NEW.muted,NEW.revision)
              IS NOT DISTINCT FROM ROW(OLD.tenant_id,OLD.project_id,OLD.actor_ref,OLD.conversation_id,OLD.archived,OLD.muted,OLD.revision) THEN RETURN NULL; END IF;
        END IF;
        IF ROW(NEW.tenant_id,NEW.project_id,NEW.actor_ref,NEW.conversation_id) IS DISTINCT FROM
           ROW(OLD.tenant_id,OLD.project_id,OLD.actor_ref,OLD.conversation_id) THEN
            PERFORM acs_conversation_private_refresh(OLD.tenant_id,OLD.project_id,OLD.conversation_id,OLD.actor_ref);
        END IF;
    END IF;
    IF TG_OP='DELETE' THEN
        PERFORM acs_conversation_private_refresh(OLD.tenant_id,OLD.project_id,OLD.conversation_id,OLD.actor_ref);
    ELSE
        PERFORM acs_conversation_private_refresh(NEW.tenant_id,NEW.project_id,NEW.conversation_id,NEW.actor_ref);
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_conversation_messages AFTER INSERT ON communication_messages
FOR EACH ROW EXECUTE FUNCTION acs_conversation_message_version();
CREATE TRIGGER acs_conversation_read_state AFTER INSERT OR UPDATE OR DELETE ON communication_client_read_state
FOR EACH ROW EXECUTE FUNCTION acs_conversation_private_version();
CREATE TRIGGER acs_conversation_preferences AFTER INSERT OR UPDATE OR DELETE ON communication_client_preferences
FOR EACH ROW EXECUTE FUNCTION acs_conversation_private_version();
