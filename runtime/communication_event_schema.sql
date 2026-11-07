-- Committed source intent and separately ordered publication; no message body copy.
CREATE TABLE communication_event_intents (
    intent_id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, source_key TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('message.committed','reply.linked','delivery.changed','receiver.observed',
      'capability.changed','notice.created','notice.updated','conversation.updated','read_state.changed',
      'draft.changed','attachment.ready','native_link.changed','permission.changed','resync.required','stream.end')),
    resource_ref TEXT, resource_revision BIGINT NOT NULL CHECK(resource_revision>=0),
    audience_kind TEXT NOT NULL CHECK(audience_kind IN ('message','private','conversation','receiver','notice','control')),
    sender TEXT, recipient TEXT, actor_ref TEXT, scope_id TEXT,
    payload_json JSONB NOT NULL CHECK(jsonb_typeof(payload_json)='object'
      AND payload_json-ARRAY['reason_code','message_handle','conversation_id','operation_ref','reset_required']='{}'::jsonb),
    committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), published_sequence BIGINT,
    UNIQUE(tenant_id,project_id,source_key), UNIQUE(tenant_id,project_id,intent_id),
    UNIQUE(tenant_id,project_id,published_sequence),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CHECK((audience_kind='message' AND sender IS NOT NULL AND recipient IS NOT NULL) OR
          (audience_kind='private' AND actor_ref IS NOT NULL) OR
          (audience_kind='conversation' AND recipient IS NOT NULL) OR
          (audience_kind='receiver' AND scope_id IS NOT NULL) OR
          (audience_kind='notice' AND recipient IS NOT NULL) OR audience_kind='control'),
    CHECK(published_sequence IS NULL OR published_sequence>0)
);
CREATE INDEX communication_event_pending ON communication_event_intents(tenant_id,project_id,intent_id)
WHERE published_sequence IS NULL;
CREATE TABLE communication_event_clocks (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
    high_water BIGINT NOT NULL DEFAULT 0 CHECK(high_water>=0),
    retained_through BIGINT NOT NULL DEFAULT 0 CHECK(retained_through>=0 AND retained_through<=high_water),
    PRIMARY KEY(tenant_id,project_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id)
);
CREATE TABLE communication_event_stream (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, sequence BIGINT NOT NULL CHECK(sequence>0),
    intent_id BIGINT NOT NULL UNIQUE, event_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL, resource_ref TEXT, resource_revision BIGINT NOT NULL CHECK(resource_revision>=0),
    audience_kind TEXT NOT NULL, sender TEXT, recipient TEXT, actor_ref TEXT, scope_id TEXT,
    payload_json JSONB NOT NULL, committed_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,sequence),
    FOREIGN KEY(tenant_id,project_id,intent_id) REFERENCES communication_event_intents(tenant_id,project_id,intent_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES communication_event_clocks(tenant_id,project_id)
);
CREATE INDEX communication_event_expiry ON communication_event_stream(tenant_id,project_id,published_at,sequence);
CREATE FUNCTION acs_communication_event_intent(p_tenant TEXT,p_project TEXT,p_key TEXT,p_kind TEXT,p_ref TEXT,
    p_revision BIGINT,p_audience TEXT,p_sender TEXT,p_recipient TEXT,p_actor TEXT,p_scope TEXT,p_payload JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO communication_event_intents(tenant_id,project_id,source_key,event_id,kind,resource_ref,
      resource_revision,audience_kind,sender,recipient,actor_ref,scope_id,payload_json)
    VALUES(p_tenant,p_project,p_key,'event-'||encode(sha256(convert_to(jsonb_build_array(p_tenant,p_project,p_key)::text,'UTF8')),'hex'),
      p_kind,p_ref,p_revision,p_audience,p_sender,p_recipient,p_actor,p_scope,p_payload)
    ON CONFLICT(tenant_id,project_id,source_key) DO UPDATE SET source_key=EXCLUDED.source_key
    WHERE ROW(communication_event_intents.kind,communication_event_intents.resource_ref,communication_event_intents.resource_revision,
      communication_event_intents.audience_kind,communication_event_intents.sender,communication_event_intents.recipient,
      communication_event_intents.actor_ref,communication_event_intents.scope_id,communication_event_intents.payload_json)
      IS NOT DISTINCT FROM ROW(EXCLUDED.kind,EXCLUDED.resource_ref,EXCLUDED.resource_revision,EXCLUDED.audience_kind,
        EXCLUDED.sender,EXCLUDED.recipient,EXCLUDED.actor_ref,EXCLUDED.scope_id,EXCLUDED.payload_json);
    IF NOT FOUND THEN RAISE EXCEPTION 'communication_event_intent_identity_conflict'; END IF;
END;
$$;
CREATE FUNCTION acs_communication_message_events() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ref TEXT; delivery_revision BIGINT; operation_ref TEXT;
BEGIN
    ref:='message:'||NEW.project_id||':'||NEW.message_id;
    SELECT v.revision,m.operation_id INTO delivery_revision,operation_ref FROM communication_delivery_versions v
      JOIN delivery_messages m USING(tenant_id,message_id) WHERE v.tenant_id=NEW.tenant_id AND v.message_id=NEW.message_id;
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,'message:'||NEW.message_id,
      'message.committed',ref,1,'message',NEW.sender,NEW.recipient,NULL,NULL,
      jsonb_build_object('message_handle',ref));
    IF delivery_revision IS NOT NULL THEN
      PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,'delivery:'||NEW.message_id||':'||delivery_revision,
        'delivery.changed',ref,delivery_revision,'message',NEW.sender,NEW.recipient,NULL,NULL,
        jsonb_build_object('message_handle',ref,'operation_ref',operation_ref));
    END IF;
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_communication_reply_events() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original communication_messages%ROWTYPE; revision BIGINT; ref TEXT;
BEGIN
    SELECT * INTO STRICT original FROM communication_messages WHERE tenant_id=NEW.tenant_id
      AND project_id=NEW.project_id AND message_id=NEW.request_id;
    SELECT 1+count(*) INTO revision FROM communication_replies WHERE tenant_id=NEW.tenant_id
      AND project_id=NEW.project_id AND request_id=NEW.request_id;
    ref:='message:'||NEW.project_id||':'||NEW.request_id;
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,'reply:'||NEW.request_id||':'||NEW.reply_id,
      'reply.linked',ref,revision,'message',original.sender,original.recipient,NULL,NULL,
      jsonb_build_object('message_handle',ref));
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_communication_delivery_events() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE message communication_messages%ROWTYPE; ref TEXT; operation_ref TEXT;
BEGIN
    IF TG_OP='UPDATE' AND NEW.revision=OLD.revision THEN RETURN NULL; END IF;
    SELECT * INTO message FROM communication_messages WHERE tenant_id=NEW.tenant_id AND message_id=NEW.message_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    ref:='message:'||message.project_id||':'||NEW.message_id;
    SELECT operation_id INTO operation_ref FROM delivery_messages WHERE tenant_id=NEW.tenant_id AND message_id=NEW.message_id;
    PERFORM acs_communication_event_intent(NEW.tenant_id,message.project_id,'delivery:'||NEW.message_id||':'||NEW.revision,
      'delivery.changed',ref,NEW.revision,'message',message.sender,message.recipient,NULL,NULL,
      jsonb_build_object('message_handle',ref,'operation_ref',operation_ref));
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_communication_private_events() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE kind TEXT;
BEGIN
    kind:=CASE WHEN TG_TABLE_NAME='communication_client_read_state' THEN 'read_state.changed' ELSE 'draft.changed' END;
    IF TG_OP='UPDATE' AND NEW.revision=OLD.revision THEN RETURN NULL; END IF;
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,
      encode(sha256(convert_to(jsonb_build_array(kind,NEW.actor_ref,NEW.conversation_id,NEW.revision)::text,'UTF8')),'hex'),
      kind,NEW.conversation_id,NEW.revision,'private',NULL,NULL,NEW.actor_ref,NULL,
      jsonb_build_object('conversation_id',NEW.conversation_id));
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_communication_message_events AFTER INSERT ON communication_messages
FOR EACH ROW EXECUTE FUNCTION acs_communication_message_events();
CREATE TRIGGER acs_communication_reply_events AFTER INSERT ON communication_replies
FOR EACH ROW EXECUTE FUNCTION acs_communication_reply_events();
CREATE TRIGGER acs_communication_delivery_events AFTER INSERT OR UPDATE ON communication_delivery_versions
FOR EACH ROW EXECUTE FUNCTION acs_communication_delivery_events();
CREATE TRIGGER acs_communication_read_events AFTER INSERT OR UPDATE ON communication_client_read_state
FOR EACH ROW EXECUTE FUNCTION acs_communication_private_events();
CREATE TRIGGER acs_communication_draft_events AFTER INSERT OR UPDATE ON communication_client_drafts
FOR EACH ROW EXECUTE FUNCTION acs_communication_private_events();
-- Existing committed data is read by snapshots. Adoption creates no fake past facts.
INSERT INTO communication_event_clocks(tenant_id,project_id) SELECT tenant_id,project_id FROM collaboration_projects;
