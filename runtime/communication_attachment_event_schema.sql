CREATE FUNCTION acs_attachment_ready_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state<>'ready' OR (TG_OP='UPDATE' AND NEW.revision=OLD.revision) THEN RETURN NULL; END IF;
    PERFORM acs_communication_event_intent(NEW.tenant_id,NEW.project_id,
      encode(sha256(convert_to(jsonb_build_array('attachment.ready',NEW.attachment_id,NEW.revision)::text,'UTF8')),'hex'),
      'attachment.ready',NEW.attachment_id,NEW.revision,'private',NULL,NEW.owner_address,NEW.viewer_key,NEW.scope_id,'{}');
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_attachment_ready_event AFTER INSERT OR UPDATE ON communication_attachments
FOR EACH ROW EXECUTE FUNCTION acs_attachment_ready_event();
