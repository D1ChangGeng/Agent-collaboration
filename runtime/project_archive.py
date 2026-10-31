"""Read-only original delivery packets and stored Native results. No task execution."""
from __future__ import annotations

import json

from runtime.errors import NotFound
from runtime.project_common import canonical, handle, parse_handle
from runtime.project_source import read_response_artifact
from runtime.source import SourceReadbackError


def _bound(value, args):
    maximum = args.get("max_inline_bytes", 16384)
    if type(maximum) is not int or not 1 <= maximum <= 65536 or len(canonical(value).encode()) > maximum:
        raise ValueError("archived content exceeds the requested inline bound")


def read_archived_message(self, authority, cursor, _project, command, args, _credential):
    kind = args["handle"].split(":", 1)[0]
    if kind not in {"message", "response"}:
        raise ValueError("message or response handle required")
    message_id = parse_handle(args["handle"], kind, args["project_id"])
    cursor.execute("SELECT response_initiator_ref,author_principal_ref,recipient_slot_id,source_hash "
                   "FROM communication_archives WHERE tenant_id=%s AND project_id=%s AND message_id=%s",
                   (self.context.tenant_id, args["project_id"], message_id))
    row = cursor.fetchone()
    if row is None or (kind == "response" and row[0] is None):
        raise NotFound("message", message_id)
    observed = authority.read_message(command.model_copy(update={
        "command_type": "message.read", "target_kind": "message", "target_id": message_id,
    }), message_id)
    message = observed["message"]
    if message["canonical_hash"] != row[3]:
        raise SourceReadbackError("archived message differs from its adopted identity")
    consumed = False
    data = {"project_id": args["project_id"], "message_id": message_id,
        "response_handle": handle("response", args["project_id"], message_id),
        "state": message["state"], "receipt_high_water": message["receipt_high_water"],
        "operation_id": message["operation_id"], "receipts": observed["receipts"],
        "recorded_author": {"principal_ref": row[1], "agent_slot_id": None},
        "recorded_recipient": {"agent_slot_id": row[2], "principal_ref": None}}
    if kind == "message":
        if row[0] is None:
            data.pop("response_handle")
        data.update(kind="message", message_handle=handle("message", args["project_id"], message_id), consumed=consumed,
                    content=message["packet_json"])
        _bound(data, args)
    else:
        data["kind"] = "response"
        response_receipts = [evidence for layer, evidence in observed["receipts"]
                             if layer == "response_received"]
        if response_receipts:
            if len(response_receipts) != 1:
                raise SourceReadbackError("response receipt identity is ambiguous")
            receipt = response_receipts[0]
            response_digest = receipt.get("response_digest")
            if (not isinstance(response_digest, str)
                    or receipt.get("response_artifact_ref") != "artifact:" + response_digest):
                raise SourceReadbackError("response receipt has no exact artifact identity")
            data["response_artifact"] = {
                "opaque_ref": receipt["response_artifact_ref"],
                "sha256": response_digest,
                "content_state": "provider_unavailable",
            }
            artifact_store = self.sources.store if self.sources is not None else self.artifacts
            if artifact_store is not None:
                reference, payload = read_response_artifact(
                    artifact_store,
                    message["packet_json"]["target_scope_id"], response_digest,
                    args.get("max_inline_bytes", 16384), authority, command,
                )
                data["response_artifact"] = {
                    **reference.model_dump(mode="json"),
                    "opaque_ref": receipt["response_artifact_ref"],
                    "content_state": "inline" if payload is not None else "verified_reference",
                }
                if payload is not None:
                    try:
                        data["response"] = json.loads(payload)
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise SourceReadbackError(
                            "response artifact is not canonical JSON"
                        ) from error
        has_observations = False
        if authority.access_mode == "owner":
            cursor.execute("SELECT to_regclass('native_response_observations')")
            has_observations = cursor.fetchone()[0] is not None
        if has_observations:
            cursor.execute("SELECT projection_id,attempt_id,dispatch_id,native_outcome,response_digest,observed_at "
                "FROM native_response_observations WHERE tenant_id=%s AND message_id=%s "
                "AND disposition='fenced_late' ORDER BY observed_at,projection_id",
                (authority.tenant_id,message_id))
            historical=[]
            store=self.sources.store if self.sources is not None else self.artifacts
            for projection,attempt,dispatch,outcome,response_digest,observed_at in cursor.fetchall():
                item={"projection_id":projection,"attempt_id":attempt,"dispatch_id":dispatch,
                    "native_outcome":outcome,"disposition":"fenced_late","observed_at":observed_at.isoformat(),
                    "response_artifact":{"opaque_ref":"artifact:"+response_digest,"sha256":response_digest,
                                         "content_state":"provider_unavailable"}}
                if store is not None:
                    reference,payload=read_response_artifact(store,message["packet_json"]["target_scope_id"],
                        response_digest,args.get("max_inline_bytes",16384),authority,command)
                    item["response_artifact"]={**reference.model_dump(mode="json"),
                        "opaque_ref":"artifact:"+response_digest,
                        "content_state":"inline" if payload is not None else "verified_reference"}
                    if payload is not None:
                        item["response"]=json.loads(payload)
                historical.append(item)
            if historical:
                data["historical_responses"]=historical
    return "observed", data, []
