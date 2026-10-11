"""Historical result view keeps recorded bytes and current task state separate."""
import json

import psycopg

from runtime.artifacts import LocalArtifactStore
from runtime_tests.test_project_service import work_args,send_args

pytest_plugins=("runtime_tests.test_project_service",)


def test_owner_reads_recorded_late_result_without_changing_current_receipts(project,tmp_path):
    f=project
    f.authority.access_mode="owner"
    f.projects.execute("create_work",work_args(),f.credential)
    sent=f.projects.execute("send_message",send_args(),f.credential)[1]
    # Persisted observation fixture tests the read interface, not native provenance.
    with LocalArtifactStore(tmp_path/"artifacts",scope_id="local-scope") as store:
        value={"text":"recorded late terminal output"}
        raw=json.dumps(value).encode()
        ref=store.put_bytes(raw,kind="readback",media_type="application/json")
        f.projects.artifacts=store
        with psycopg.connect(f.dsn) as conn:
            conn.execute("UPDATE delivery_messages SET state='expired' WHERE message_id=%s",(sent["message_id"],))
            conn.execute("INSERT INTO native_response_observations(tenant_id,projection_id,receipt_id,message_id,operation_id,"
                "invocation_id,attempt_id,dispatch_id,endpoint_id,binding_revision,machine_id,node_id,boot_incarnation,"
                "accepted_revision,accepted_state_digest,native_response_ref,native_outcome,response_artifact_ref,"
                "response_digest,evidence_digest,observed_at,canonical_digest,disposition) "
                "VALUES ('local-tenant','fixture-late','fixture-late-receipt',%s,%s,'fixture-invocation','fixture-attempt',"
                "'fixture-dispatch','fixture-endpoint',1,'fixture-machine','fixture-node','fixture-boot',0,%s,"
                "'fixture-native-response','completed',%s,%s,%s,clock_timestamp(),%s,'fenced_late')",
                (sent["message_id"],sent["operation_id"],"a"*64,"artifact:"+ref.sha256,ref.sha256,ref.sha256,"b"*64))
        result=f.projects.execute("read_message",{"project_id":"project-alpha","handle":sent["response_handle"],"consume":False},f.credential)[1]
        assert result["state"]=="expired"
        assert result["receipt_high_water"]=="accepted_by_authority"
        assert result["historical_responses"][0]["response"]==value
        assert result["historical_responses"][0]["disposition"]=="fenced_late"
