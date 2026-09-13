-- Runtime 1.11: bind one native session to its immutable delivery/Driver attempt.
ALTER TABLE harness_session_bindings ADD COLUMN IF NOT EXISTS attempt_context JSONB;
ALTER TABLE harness_session_bindings ADD COLUMN IF NOT EXISTS attached_event_id BIGINT;
ALTER TABLE native_response_observations ADD COLUMN IF NOT EXISTS harness_proof JSONB;

CREATE INDEX IF NOT EXISTS harness_session_attempt_lookup
    ON harness_session_bindings(tenant_id, work_item_id, revision)
    WHERE attempt_context IS NOT NULL;
