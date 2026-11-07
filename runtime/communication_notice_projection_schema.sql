-- One real Notice DTO revision per actual recipient/principal viewer.
CREATE TABLE communication_notice_view_versions (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, message_id TEXT NOT NULL,
    recipient TEXT NOT NULL, actor_ref TEXT NOT NULL,
    source_revision BIGINT NOT NULL CHECK(source_revision>=1),
    seen_revision BIGINT NOT NULL CHECK(seen_revision>=0),
    revision BIGINT NOT NULL CHECK(revision>=source_revision+seen_revision),
    PRIMARY KEY(tenant_id,project_id,message_id,recipient,actor_ref),
    FOREIGN KEY(tenant_id,project_id,message_id,recipient)
      REFERENCES communication_client_notice_versions(tenant_id,project_id,message_id,recipient) ON DELETE CASCADE
);
CREATE FUNCTION acs_notice_projection_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE who TEXT; private_revision BIGINT;
BEGIN
    FOR who IN
      SELECT principal_ref FROM collaboration_memberships WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND 'collaborator:'||NEW.project_id||':'||agent_slot_id=NEW.recipient
      UNION SELECT principal_ref FROM collaboration_team_members WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND 'collaborator:'||NEW.project_id||':'||agent_slot_id=NEW.recipient
      UNION SELECT principal_ref FROM communication_clients WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND address=NEW.recipient
      UNION SELECT actor_ref FROM communication_client_notice_seen WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND message_id=NEW.message_id AND recipient=NEW.recipient
    LOOP
      SELECT revision INTO private_revision FROM communication_client_notice_seen WHERE tenant_id=NEW.tenant_id
        AND project_id=NEW.project_id AND message_id=NEW.message_id AND recipient=NEW.recipient AND actor_ref=who;
      private_revision:=COALESCE(private_revision,0);
      INSERT INTO communication_notice_view_versions VALUES(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient,who,
        NEW.revision,private_revision,NEW.revision+private_revision)
      ON CONFLICT(tenant_id,project_id,message_id,recipient,actor_ref) DO UPDATE
      SET source_revision=GREATEST(communication_notice_view_versions.source_revision,EXCLUDED.source_revision),
          revision=communication_notice_view_versions.revision+
            GREATEST(EXCLUDED.source_revision-communication_notice_view_versions.source_revision,0);
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE FUNCTION acs_notice_projection_seen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE public_revision BIGINT;
BEGIN
    IF TG_OP='DELETE' THEN
      UPDATE communication_notice_view_versions SET seen_revision=0,revision=revision+1 WHERE
        (tenant_id,project_id,message_id,recipient,actor_ref)=
        (OLD.tenant_id,OLD.project_id,OLD.message_id,OLD.recipient,OLD.actor_ref);
      RETURN NULL;
    END IF;
    IF TG_OP='UPDATE' AND ROW(NEW.seen,NEW.revision) IS NOT DISTINCT FROM ROW(OLD.seen,OLD.revision) THEN
      RETURN NULL;
    END IF;
    SELECT revision INTO STRICT public_revision FROM communication_client_notice_versions WHERE tenant_id=NEW.tenant_id
      AND project_id=NEW.project_id AND message_id=NEW.message_id AND recipient=NEW.recipient;
    INSERT INTO communication_notice_view_versions VALUES(NEW.tenant_id,NEW.project_id,NEW.message_id,NEW.recipient,NEW.actor_ref,
      public_revision,NEW.revision,public_revision+NEW.revision)
    ON CONFLICT(tenant_id,project_id,message_id,recipient,actor_ref) DO UPDATE
    SET seen_revision=EXCLUDED.seen_revision,
        revision=communication_notice_view_versions.revision+
          GREATEST(EXCLUDED.seen_revision-communication_notice_view_versions.seen_revision,1);
    RETURN NULL;
END;
$$;
CREATE TRIGGER acs_notice_projection_source AFTER INSERT OR UPDATE OF revision ON communication_client_notice_versions
FOR EACH ROW EXECUTE FUNCTION acs_notice_projection_source();
CREATE TRIGGER acs_notice_projection_seen AFTER INSERT OR UPDATE OR DELETE ON communication_client_notice_seen
FOR EACH ROW EXECUTE FUNCTION acs_notice_projection_seen();
-- Existing facts seed versions only; event producers are adopted separately.
INSERT INTO communication_notice_view_versions
SELECT v.tenant_id,v.project_id,v.message_id,v.recipient,a.actor_ref,v.revision,COALESCE(s.revision,0),v.revision+COALESCE(s.revision,0)
FROM communication_client_notice_versions v CROSS JOIN LATERAL (
  SELECT principal_ref actor_ref FROM collaboration_memberships WHERE tenant_id=v.tenant_id AND project_id=v.project_id
    AND 'collaborator:'||v.project_id||':'||agent_slot_id=v.recipient
  UNION SELECT principal_ref FROM collaboration_team_members WHERE tenant_id=v.tenant_id AND project_id=v.project_id
    AND 'collaborator:'||v.project_id||':'||agent_slot_id=v.recipient
  UNION SELECT principal_ref FROM communication_clients WHERE tenant_id=v.tenant_id AND project_id=v.project_id AND address=v.recipient
  UNION SELECT actor_ref FROM communication_client_notice_seen WHERE tenant_id=v.tenant_id AND project_id=v.project_id
    AND message_id=v.message_id AND recipient=v.recipient
) a LEFT JOIN communication_client_notice_seen s ON (s.tenant_id,s.project_id,s.message_id,s.recipient,s.actor_ref)=
  (v.tenant_id,v.project_id,v.message_id,v.recipient,a.actor_ref);
