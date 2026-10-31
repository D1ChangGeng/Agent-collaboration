-- Runtime 1.10: versioned, work-scoped native Harness session authority.
CREATE TABLE IF NOT EXISTS harness_session_heads (
    tenant_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 0),
    active_binding_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, work_item_id)
);

CREATE TABLE IF NOT EXISTS harness_session_bindings (
    tenant_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    agent_slot_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    driver_kind TEXT NOT NULL CHECK (driver_kind IN ('codex','opencode')),
    native_session_ref TEXT NOT NULL,
    installed_version TEXT NOT NULL,
    receipt_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','retired')),
    attached_by TEXT NOT NULL,
    attached_command_id TEXT NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    retired_by TEXT,
    retired_command_id TEXT,
    retired_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, binding_id),
    UNIQUE (tenant_id, work_item_id, revision),
    FOREIGN KEY (tenant_id, work_item_id)
      REFERENCES harness_session_heads(tenant_id, work_item_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS harness_session_one_active_work
    ON harness_session_bindings(tenant_id, work_item_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS harness_session_one_active_native
    ON harness_session_bindings(tenant_id, driver_kind, native_session_ref) WHERE status='active';

CREATE TABLE IF NOT EXISTS harness_session_result_admissions (
    tenant_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    native_session_ref TEXT NOT NULL,
    result_ref TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('current','fenced_late')),
    command_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, result_id),
    UNIQUE (tenant_id, command_id),
    FOREIGN KEY (tenant_id, binding_id)
      REFERENCES harness_session_bindings(tenant_id, binding_id)
);
