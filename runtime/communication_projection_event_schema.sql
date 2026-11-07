-- Real projection counters are committed beside their invalidation intents.
CREATE FUNCTION acs_projection_conversation_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.revision=0 OR (TG_OP='UPDATE' AND NEW.revision=OLD.revision) THEN RETURN NULL; END IF;
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,
      encode(sha256(convert_to(jsonb_build_array('conversation',NEW.viewer_address,NEW.peer_address,NEW.revision)::text,'UTF8')),'hex'),
      'conversation.updated',NEW.conversation_id,NEW.revision,'conversation',NEW.peer_address,NEW.viewer_address,NEW.actor_ref,NULL,
      jsonb_build_object('conversation_id',NEW.conversation_id));
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_projection_notice_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE public_ref TEXT;
BEGIN
    IF TG_OP='UPDATE' AND NEW.revision=OLD.revision THEN RETURN NULL; END IF;
    SELECT 'notification:'||NEW.project_id||':'||notice_ref INTO STRICT public_ref FROM communication_client_notice_versions
      WHERE (tenant_id,project_id,message_id,recipient)=(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient);
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,
      encode(sha256(convert_to(jsonb_build_array('notice.updated',public_ref,NEW.actor_ref,NEW.revision)::text,'UTF8')),'hex'),
      'notice.updated',public_ref,NEW.revision,'notice',NULL,NEW.recipient,NEW.actor_ref,NULL,'{}');
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_projection_notice_created() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE view_row communication_notice_view_versions%ROWTYPE; public_ref TEXT;
BEGIN
    SELECT 'notification:'||NEW.project_id||':'||notice_ref INTO STRICT public_ref FROM communication_client_notice_versions
      WHERE (tenant_id,project_id,message_id,recipient)=(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient);
    FOR view_row IN SELECT * FROM communication_notice_view_versions WHERE
      (tenant_id,project_id,message_id,recipient)=(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient)
    LOOP
      PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,
        encode(sha256(convert_to(jsonb_build_array('notice.created',public_ref,view_row.actor_ref)::text,'UTF8')),'hex'),
        'notice.created',public_ref,view_row.revision,'notice',NULL,NEW.recipient,view_row.actor_ref,NULL,'{}');
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_projection_conversation_event AFTER INSERT OR UPDATE ON communication_conversation_versions
FOR EACH ROW EXECUTE FUNCTION acs_projection_conversation_event();
CREATE TRIGGER acs_projection_notice_event AFTER INSERT OR UPDATE ON communication_notice_view_versions
FOR EACH ROW EXECUTE FUNCTION acs_projection_notice_event();
CREATE TRIGGER acs_projection_notice_created AFTER INSERT ON communication_notices
FOR EACH ROW EXECUTE FUNCTION acs_projection_notice_created();
