"""Owner-pinned admission for one future P1 OpenCode model lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from runtime.opencode_driver import OpenCodeLaunchProfile
from runtime.receiver_paths import PathSecurityRejected, open_validated_file, private_parent
from tools.runtime.p1_opencode_readback import validate_opencode_lineage

DECISION_ID = "P1-OPENCODE-LIFECYCLE-ONE-PROMPT-01"
MODEL_PROMPT = "Reply with exactly ACS_P1_OPENCODE_API_OK. Do not call tools."
SCHEMA_SHA256 = "cf12e9739510a196c7f25eb938555cfb66d901957f66f840a12d4489ae440ac3"
SCENE_FIELDS = {
    "schema_version", "native_executable_path", "native_executable_sha256",
    "native_executable_size", "opencode_version", "schema_sha256",
    "provider_id", "provider_url", "model_id", "agent", "auth_key_ref_path",
    "auth_key_ref_path_sha256", "config_sha256", "max_prompt_async",
    "max_collect_reads", "max_elapsed_seconds", "budget_evidence_ref",
}


class OpenCodeGateRejected(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _owner_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    if os.name != "posix" or not path.is_absolute():
        raise OpenCodeGateRejected("owner-only OpenCode decision requires POSIX absolute path")
    try:
        descriptor, _ = open_validated_file(path, private=True)
    except (OSError, PathSecurityRejected) as error:
        raise OpenCodeGateRejected("OpenCode owner file path is unsafe") from error
    try:
        data = bytearray()
        while chunk := os.read(descriptor, min(65536, 100_001 - len(data))):
            data.extend(chunk)
            if len(data) > 100_000:
                break
    finally:
        os.close(descriptor)
    if len(data) > 100_000 or _sha(data) != expected_sha256:
        raise OpenCodeGateRejected("OpenCode owner file digest differs")
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError):
        raise OpenCodeGateRejected("OpenCode owner JSON is malformed") from None
    if not isinstance(value, dict):
        raise OpenCodeGateRejected("OpenCode owner JSON is not an object")
    return value


def validate_scene(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != SCENE_FIELDS:
        raise OpenCodeGateRejected("OpenCode scene fields differ")
    if (
        value["schema_version"] != "acs-p1-opencode-scene/1"
        or value["opencode_version"] != "1.18.30"
        or value["schema_sha256"] != SCHEMA_SHA256
        or value["agent"] != "engineer"
        or type(value["native_executable_size"]) is not int
        or not 1_000_000 <= value["native_executable_size"] <= 500_000_000
        or type(value["max_prompt_async"]) is not int
        or value["max_prompt_async"] != 1
        or type(value["max_collect_reads"]) is not int
        or not 1 <= value["max_collect_reads"] <= 6
        or type(value["max_elapsed_seconds"]) is not int
        or value["max_elapsed_seconds"] != 120
        or value["budget_evidence_ref"] != DECISION_ID
    ):
        raise OpenCodeGateRejected("OpenCode scene version or one-prompt bound differs")
    for name in ("native_executable_path", "auth_key_ref_path"):
        path = value[name]
        if (
            not isinstance(path, str)
            or not PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or any(ord(character) < 32 for character in path)
        ):
            raise OpenCodeGateRejected("OpenCode host file reference is unsafe")
    for name in (
        "native_executable_sha256", "auth_key_ref_path_sha256", "config_sha256",
    ):
        if not isinstance(value[name], str) or not re.fullmatch(r"[a-f0-9]{64}", value[name]):
            raise OpenCodeGateRejected("OpenCode artifact digest is malformed")
    if value["auth_key_ref_path_sha256"] != _sha(value["auth_key_ref_path"].encode()):
        raise OpenCodeGateRejected("OpenCode key reference path pin differs")
    for name in ("provider_id", "model_id"):
        if not isinstance(value[name], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", value[name]):
            raise OpenCodeGateRejected("OpenCode provider/model identifier is malformed")
    url = value["provider_url"]
    if not isinstance(url, str) or len(url) > 2048 or any(ord(char) < 32 for char in url):
        raise OpenCodeGateRejected("OpenCode provider route is malformed")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise OpenCodeGateRejected("OpenCode provider route is malformed") from error
    if (
        parsed.scheme != "https" or not parsed.hostname
        or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", parsed.hostname)
        or port is not None and not 1 <= port <= 65535
        or parsed.username is not None or parsed.password is not None
        or parsed.fragment or parsed.query or not parsed.path.startswith("/")
    ):
        raise OpenCodeGateRejected("OpenCode provider route is outside reviewed HTTPS form")
    return value


@dataclass(frozen=True)
class OpenCodeGateAdmission:
    scene: dict[str, Any]
    scene_sha256: str
    budget_sha256: str
    source_commit: str
    source_tree: str
    run_id: str
    machine_id: str
    node_id: str

    @classmethod
    def load(
        cls,
        scene_path: Path,
        scene_sha256: str,
        budget_path: Path,
        budget_sha256: str,
        *,
        source_commit: str,
        source_tree: str,
        run_id: str,
        machine_id: str,
        node_id: str,
    ) -> OpenCodeGateAdmission:
        scene = validate_scene(_owner_json(scene_path, scene_sha256))
        decision = _owner_json(budget_path, budget_sha256)
        if (
            not re.fullmatch(r"[a-f0-9]{40}", source_commit)
            or not re.fullmatch(r"[a-f0-9]{40}", source_tree)
            or not re.fullmatch(r"p1-run-[a-f0-9]{32}", run_id)
            or not isinstance(machine_id, str) or not machine_id
            or not isinstance(node_id, str) or not node_id
            or set(decision) != {
                "schema_version", "decision_id", "source_commit", "source_tree",
                "scene_profile_sha256", "scenario_id", "run_id", "machine_id", "node_id",
                "provider_id", "model_id",
                "prompt", "max_prompt_async", "max_collect_reads",
                "max_elapsed_seconds", "tool_policy", "retry_policy", "spend_status",
            }
            or decision["schema_version"] != "acs-p1-model-request-budget/1"
            or decision["decision_id"] != DECISION_ID
            or decision["source_commit"] != source_commit
            or decision["source_tree"] != source_tree
            or decision["run_id"] != run_id
            or decision["machine_id"] != machine_id
            or decision["node_id"] != node_id
            or decision["scene_profile_sha256"] != scene_sha256
            or decision["scenario_id"] != "P1-OPENCODE-LIFECYCLE"
            or decision["provider_id"] != scene["provider_id"]
            or decision["model_id"] != scene["model_id"]
            or decision["prompt"] != MODEL_PROMPT
            or type(decision["max_prompt_async"]) is not int
            or decision["max_prompt_async"] != 1
            or type(decision["max_collect_reads"]) is not int
            or decision["max_collect_reads"] != scene["max_collect_reads"]
            or type(decision["max_elapsed_seconds"]) is not int
            or decision["max_elapsed_seconds"] != 120
            or not isinstance(decision["tool_policy"], str)
            or "No tool invocation" not in decision["tool_policy"]
            or not isinstance(decision["retry_policy"], str)
            or "No second prompt_async" not in decision["retry_policy"]
            or not isinstance(decision["spend_status"], str)
            or "monetary cap not observed" not in decision["spend_status"]
        ):
            raise OpenCodeGateRejected("OpenCode one-prompt Management decision differs")
        return cls(
            scene, scene_sha256, budget_sha256, source_commit, source_tree,
            run_id, machine_id, node_id,
        )

    def assert_native_profile(self, profile: OpenCodeLaunchProfile) -> None:
        if (
            profile.version != self.scene["opencode_version"]
            or profile.executable_sha256 != self.scene["native_executable_sha256"]
            or profile.schema_sha256 != self.scene["schema_sha256"]
            or profile.config_sha256 != self.scene["config_sha256"]
            or profile.provider_id != self.scene["provider_id"]
            or profile.model_id != self.scene["model_id"]
            or profile.agent != self.scene["agent"]
        ):
            raise OpenCodeGateRejected("OpenCode actual Driver profile differs from scene pin")

    def key_reference_identity(self) -> tuple[int, int, int, int, int]:
        """Attest the owner key file without reading or copying key bytes."""
        path = Path(self.scene["auth_key_ref_path"])
        if os.name != "posix" or not hasattr(os, "O_PATH"):
            raise OpenCodeGateRejected("OpenCode key attestation requires POSIX O_PATH")
        parent = None
        descriptor = None
        try:
            parent, _ = private_parent(path.parent)
            descriptor = os.open(
                path.name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            info = os.fstat(descriptor)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise OpenCodeGateRejected("OpenCode key reference inode or mode differs")
            return (
                info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink
            )
        except (OSError, PathSecurityRejected) as error:
            raise OpenCodeGateRejected("OpenCode key reference path is unsafe") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent is not None:
                os.close(parent)

    def assert_final_lineage(self, readback: object) -> dict[str, Any]:
        value = validate_opencode_lineage(readback)
        if (
            value["source_commit"] != self.source_commit
            or value["source_tree"] != self.source_tree
            or value["run_id"] != self.run_id
            or value["machine_id"] != self.machine_id
            or value["node_id"] != self.node_id
        ):
            raise OpenCodeGateRejected("OpenCode final readback left exact source")
        return value
