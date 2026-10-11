-- Continuous owner requests may omit business expiry.
ALTER TABLE delivery_messages ALTER COLUMN deadline DROP NOT NULL;
ALTER TABLE delivery_attempts ALTER COLUMN deadline DROP NOT NULL;
ALTER TABLE grants ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE grants ADD COLUMN IF NOT EXISTS identity_only BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE enrolled_node_bindings ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE enrolled_runtimes ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE delivery_endpoints ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE delivery_endpoint_registrations ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE deployment_connection_refs ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE authority_transport_keys ALTER COLUMN expires_at DROP NOT NULL;
ALTER TABLE delivery_endpoint_registrations ALTER COLUMN proof_ref DROP NOT NULL;
ALTER TABLE delivery_transport_admissions ALTER COLUMN deadline DROP NOT NULL;
CREATE TABLE IF NOT EXISTS owner_node_commands (
    tenant_id TEXT NOT NULL, command_id TEXT NOT NULL, node_id TEXT NOT NULL,
    node_binding_revision BIGINT NOT NULL, purpose TEXT NOT NULL,
    command_json JSONB NOT NULL, input_json JSONB NOT NULL,
    canonical_hash TEXT NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, command_id)
);
