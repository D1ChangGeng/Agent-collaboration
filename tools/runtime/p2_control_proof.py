"""Signed one-use control-channel challenge for P2 fault execution."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nacl.signing import SigningKey

from runtime.operator_files import read_operator_file
from runtime.receiver_crypto import public_key, sign, verify


def _read(path: Path) -> dict:
    value = json.loads(read_operator_file(path, maximum=16384))
    if not isinstance(value, dict):
        raise ValueError("control proof must be an object")
    return value


def _write(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".control-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def issue(path: Path, *, run_id: str, expected_host: str, expected_session: str,
          ttl_seconds: int = 30) -> dict:
    now = datetime.now(UTC)
    value = {
        "schema_version": "acs-p2-control-challenge/1",
        "run_id": run_id, "nonce": secrets.token_hex(32),
        "expected_host": expected_host, "expected_session": expected_session,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    _write(path, value)
    return value


def answer(challenge_path: Path, key_path: Path, output: Path, *, host: str,
           session: str) -> dict:
    challenge = _read(challenge_path)
    key = SigningKey(bytes.fromhex(read_operator_file(key_path, maximum=64).decode("ascii")))
    body = {
        "schema_version": "acs-p2-control-proof/1",
        "run_id": challenge["run_id"], "nonce": challenge["nonce"],
        "host": host, "session": session,
        "challenge_issued_at": challenge["issued_at"],
        "challenge_expires_at": challenge["expires_at"],
        "signed_at": datetime.now(UTC).isoformat(),
        "public_key": public_key(key),
    }
    value = {"body": body, "signature": sign(key, body)}
    _write(output, value)
    return value


def validate(challenge_path: Path, proof_path: Path, *, expected_public_key: str,
             expected_host: str, expected_session: str) -> dict:
    challenge, proof = _read(challenge_path), _read(proof_path)
    if set(proof) != {"body", "signature"} or not isinstance(proof["body"], dict):
        raise ValueError("control proof shape differs")
    body = proof["body"]
    verify(expected_public_key, proof["signature"], body)
    now = datetime.now(UTC)
    issued = datetime.fromisoformat(challenge["issued_at"])
    expires = datetime.fromisoformat(challenge["expires_at"])
    signed = datetime.fromisoformat(body["signed_at"])
    expected = (
        "acs-p2-control-proof/1", challenge["run_id"], challenge["nonce"],
        expected_host, expected_session, challenge["issued_at"],
        challenge["expires_at"], expected_public_key,
    )
    actual = (
        body.get("schema_version"), body.get("run_id"), body.get("nonce"),
        body.get("host"), body.get("session"), body.get("challenge_issued_at"),
        body.get("challenge_expires_at"), body.get("public_key"),
    )
    if actual != expected or not issued <= signed <= expires or not issued <= now <= expires:
        raise ValueError("control proof identity or time differs")
    proof_path.unlink()
    return {
        "verified": True, "run_id": body["run_id"], "host": body["host"],
        "session": body["session"], "signed_at": body["signed_at"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("answer")
    command.add_argument("--challenge", type=Path, required=True)
    command.add_argument("--key", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--host", required=True); command.add_argument("--session", required=True)
    args = parser.parse_args()
    result = answer(args.challenge, args.key, args.output, host=args.host, session=args.session)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
