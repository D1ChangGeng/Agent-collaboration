"""Body budgets and continuations through public tools and real PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from runtime_tests.test_communication import call, rejected, send, wait
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture


def exchange(comm, original="Please send the details", response="汉🙂line\n" * 1000):
    request = send(comm, content=original, activation="message_only")["data"]
    reply = send(
        comm,
        "b",
        "a",
        content=response,
        activation="message_only",
        reply_to=[request["message_handle"]],
    )["data"]
    return request, reply, response


@pytest.mark.parametrize("budget,repetitions", [(31, 20), (16384, 2000)])
def test_inline_reply_obeys_body_budget_and_can_be_read_to_completion(comm, budget, repetitions):
    request, reply, expected = exchange(comm, response="汉🙂line\n" * repetitions)
    arguments = {} if budget == 16384 else {"max_inline_bytes": budget}
    result = call(comm, "a", "read_message", handle=request["message_handle"], **arguments)
    nested = result["data"]["reply"]
    assert len(nested["content"].encode()) <= budget
    assert nested["message_handle"] == reply["message_handle"]
    assert nested["next_offset"] is not None
    parts = [nested["content"]]
    while nested["next_offset"] is not None:
        action = next(
            item
            for item in result["follow_ups"]
            if item["arguments"]["handle"] == reply["message_handle"]
        )
        result = call(
            comm,
            "a",
            action["tool"],
            **{key: value for key, value in action["arguments"].items() if key != "project_id"},
        )
        nested = result["data"]
        assert len(nested["content"].encode()) <= budget
        parts.append(nested["content"])
    assert "".join(parts) == expected
    waited = wait(comm, "a", request["message_handle"])
    observed = waited["data"]["observations"][0]
    assert observed["reply"]["message_handle"] == reply["message_handle"]
    if len(expected.encode()) > 16384:
        assert len(observed["reply"]["content"].encode()) <= 16384
        assert any(
            action["arguments"]["handle"] == reply["message_handle"]
            for action in waited["follow_ups"]
        )


def test_tiny_budget_keeps_original_and_reply_relationship_readable(comm):
    request, reply, expected = exchange(comm, original="A", response="🙂 confirmed")
    result = call(comm, "a", "read_message", handle=request["message_handle"], max_inline_bytes=1)
    assert result["data"]["content"] == "A"
    nested = result["data"]["reply"]
    assert nested["content"] == "" and nested["next_offset"] == 0
    action = next(
        item
        for item in result["follow_ups"]
        if item["arguments"]["handle"] == reply["message_handle"]
    )
    assert action["arguments"]["max_inline_bytes"] >= 4
    first = call(
        comm,
        "a",
        "read_message",
        **{key: value for key, value in action["arguments"].items() if key != "project_id"},
    )["data"]
    assert first["content"] == "🙂"
    assert (
        call(comm, "a", "read_message", handle=reply["message_handle"])["data"]["content"]
        == expected
    )


def test_original_and_reply_continuations_have_independent_handles(comm):
    request, reply, _expected = exchange(comm, original="original " * 100, response="reply " * 100)
    result = call(comm, "a", "read_message", handle=request["message_handle"], max_inline_bytes=16)
    actions = {item["arguments"]["handle"]: item for item in result["follow_ups"]}
    assert set(actions) == {request["message_handle"], reply["message_handle"]}
    for message in (request, reply):
        page = call(
            comm,
            "a",
            "read_message",
            **{
                key: value
                for key, value in actions[message["message_handle"]]["arguments"].items()
                if key != "project_id"
            },
        )["data"]
        assert page["message_handle"] == message["message_handle"]
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM communication_messages").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (1,)


def test_continuation_never_grants_a_third_party_or_revoked_reader_access(comm):
    request, reply, _expected = exchange(comm)
    result = call(comm, "a", "read_message", handle=request["message_handle"], max_inline_bytes=16)
    action = next(
        item
        for item in result["follow_ups"]
        if item["arguments"]["handle"] == reply["message_handle"]
    )
    arguments = {key: value for key, value in action["arguments"].items() if key != "project_id"}
    rejected(comm, "c", "read_message", "authorization_denied", **arguments)
    assert call(comm, "a", "read_message", **arguments)["data"]["content"]
    with comm.authority._connect() as connection:
        connection.execute(
            "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
            (comm.clients["a"].service.context.grant_ref,),
        )
    rejected(comm, "a", "read_message", "authorization_denied", **arguments)


def test_read_schema_matches_the_enforced_body_budget(comm):
    schema = comm.clients["a"].input_schema("read_message")["properties"]
    assert schema["max_inline_bytes"]["minimum"] == 1
    assert schema["max_inline_bytes"]["maximum"] == 65536
    assert schema["max_inline_bytes"]["default"] == 16384
    request, _reply, _expected = exchange(comm)
    for budget in (0, 65537):
        rejected(
            comm,
            "a",
            "read_message",
            "invalid_arguments",
            handle=request["message_handle"],
            max_inline_bytes=budget,
        )


def test_returned_next_action_can_cross_a_later_multibyte_character(comm):
    request, _reply, expected = exchange(comm, original="A🙂B汉", response="C🙂D")
    result = call(comm, "b", "read_message", handle=request["message_handle"], max_inline_bytes=1)
    chunks = [result["data"]["content"]]
    assert chunks == ["A"]
    while result["data"]["next_offset"] is not None:
        action = next(
            action
            for action in result["follow_ups"]
            if action["arguments"]["handle"] == request["message_handle"]
        )
        result = call(
            comm,
            "b",
            "read_message",
            **{key: value for key, value in action["arguments"].items() if key != "project_id"},
        )
        assert len(result["data"]["content"].encode()) <= action["arguments"]["max_inline_bytes"]
        chunks.append(result["data"]["content"])
    assert "".join(chunks) == "A🙂B汉"
    assert expected == "C🙂D"


@pytest.mark.skipif(
    os.getenv("ACS_REAL_CONTENT_MODEL_TEST") != "1",
    reason="one actual reader model plus a scripted peer is opt-in",
)
def test_actual_codex_reader_follows_long_reply_continuations(comm, tmp_path):
    from runtime_tests.test_communication import prepare_ordinary_agents
    from runtime_tests.test_communication_remote_native import launch_codex

    prepare_ordinary_agents(comm, tmp_path)
    for client in comm.clients.values():
        client.service.service.authority.access_mode = "owner"
    label = "content-tail-" + uuid.uuid4().hex[:12]
    body = (
        "Isolated report; the validation label is at the end.\n"
        + ("Field details: regular report material.\n" * 650)
        + "\nValidation label: "
        + label
    )
    assert 16384 < len(body.encode()) <= 32768
    root = Path(__file__).resolve().parents[1]
    source_files = [
        path
        for directory in (root / "runtime", root / "runtime_deployment")
        for path in directory.glob("*")
        if path.suffix in {".py", ".sql"}
    ]
    source_files += [
        Path(__file__),
        root / "runtime_tests/test_communication_remote_native.py",
        root / "docs/runtime/p2-mcp-tool-contract.json",
    ]
    manifest = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
    (tmp_path / "source-files.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    process, outputs = launch_codex(
        comm,
        tmp_path,
        os.environ["ACS_CONTENT_PROVIDER_KEY"],
        prompt="You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for its complete report through ACS. "
        "This Inbox-only exercise uses message_only. Read the entire report using the standard 16 KiB or smaller inline body budget, "
        "then report the exact validation label at its end. Use ACS MCP tools only; do not inspect or change files.",
    )
    try:
        end = time.monotonic() + 150
        while True:
            inbox = call(comm, "b", "check_inbox")["data"]["items"]
            if inbox:
                break
            assert process.poll() is None and time.monotonic() < end, (
                "A did not submit; see its public log"
            )
            time.sleep(0.2)
        original = call(comm, "b", "read_message", handle=inbox[0]["message_handle"])["data"]
        reply = call(
            comm,
            "b",
            "send_message",
            to=original["from"],
            content=body,
            reply_to=[original["message_handle"]],
            activation="message_only",
        )["data"]
        assert process.wait(timeout=240) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        for output in outputs:
            output.close()
    events = [
        json.loads(line)
        for line in (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]
    items = [event["item"] for event in events if "item" in event]
    reads = [
        item
        for item in items
        if item.get("type") == "mcp_tool_call" and item.get("tool") == "read_message"
    ]
    assert any(
        item.get("arguments", {}).get("handle") == reply["message_handle"]
        and item["arguments"].get("offset", 0) > 0
        for item in reads
    ), "A did not continue the bounded body"
    assert all(item.get("arguments", {}).get("max_inline_bytes", 16384) <= 16384 for item in reads)
    assert any(
        label in item.get("text", "") for item in items if item.get("type") == "agent_message"
    )
    assert not any(driver.calls for driver in comm.drivers.values())
    assert all(
        hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
        for name, sha in manifest.items()
    )
    (tmp_path / "reader-facts.json").write_text(
        json.dumps(
            {
                "evidence_class": "one actual Codex reader and scripted ordinary B, public ACS MCP",
                "label": label,
                "reply_handle": reply["message_handle"],
                "body_bytes": len(body.encode()),
                "read_calls": [item["arguments"] for item in reads],
                "native_calls": 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
