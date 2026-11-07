-- Explicit ownership decisions for experimental principal-only personal rows.
-- Original rows and old request receipts are retained, never guessed or deleted.
CREATE TABLE communication_client_viewer_adoptions (
    tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, legacy_actor_ref TEXT NOT NULL,
    conversation_id TEXT NOT NULL, viewer_actor_ref TEXT NOT NULL, decision_ref TEXT NOT NULL,
    adopted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(tenant_id,project_id,legacy_actor_ref,conversation_id),
    FOREIGN KEY(tenant_id,project_id) REFERENCES collaboration_projects(tenant_id,project_id),
    CHECK(legacy_actor_ref<>viewer_actor_ref)
);
CREATE FUNCTION acs_client_retired_viewer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM communication_client_viewer_adoptions a WHERE
      (a.tenant_id,a.project_id,a.legacy_actor_ref,a.conversation_id)=
      (NEW.tenant_id,NEW.project_id,NEW.actor_ref,NEW.conversation_id)) THEN
        RAISE EXCEPTION 'retired_personal_viewer_identity';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER acs_client_retired_read_viewer BEFORE INSERT OR UPDATE ON communication_client_read_state
FOR EACH ROW EXECUTE FUNCTION acs_client_retired_viewer_guard();
CREATE TRIGGER acs_client_retired_preferences_viewer BEFORE INSERT OR UPDATE ON communication_client_preferences
FOR EACH ROW EXECUTE FUNCTION acs_client_retired_viewer_guard();
CREATE TRIGGER acs_client_retired_draft_viewer BEFORE INSERT OR UPDATE ON communication_client_drafts
FOR EACH ROW EXECUTE FUNCTION acs_client_retired_viewer_guard();
