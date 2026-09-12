from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from nacl.bindings import crypto_core_ed25519_is_valid_point
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from pydantic import BaseModel

from runtime.receiver_paths import PathSecurityRejected, open_validated_file


class SignatureRejected(ValueError):
    pass


def canonical(value: BaseModel | dict[str, Any]) -> bytes:
    body = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode()


def sha256(value: bytes | BaseModel | dict[str, Any]) -> str:
    data = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(data).hexdigest()


def public_key(signing_key: SigningKey) -> str:
    return signing_key.verify_key.encode().hex()


def key_fingerprint(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()


def sign(signing_key: SigningKey, value: BaseModel | dict[str, Any]) -> str:
    return signing_key.sign(canonical(value)).signature.hex()


def verify(public_key_hex: str, signature_hex: str, value: BaseModel | dict[str, Any]) -> None:
    try:
        encoded = bytes.fromhex(public_key_hex)
        if not crypto_core_ed25519_is_valid_point(encoded):
            raise ValueError("invalid point")
        VerifyKey(encoded).verify(canonical(value), bytes.fromhex(signature_hex))
    except (BadSignatureError, ValueError, TypeError):
        raise SignatureRejected("signature rejected") from None


def load_owner_signing_key(path: str | Path) -> SigningKey:
    try:
        fd, identity = open_validated_file(path, private=True)
    except PathSecurityRejected as error:
        raise SignatureRejected(f"private-key reference {error}") from None
    try:
        raw = os.read(fd, 65)
        info = os.fstat(fd)
        observed = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
        if observed != identity:
            raise SignatureRejected("private-key reference identity changed")
    finally:
        os.close(fd)
    if len(raw) != 64:
        raise SignatureRejected("private-key reference must contain 32-byte hex seed")
    try:
        return SigningKey(bytes.fromhex(raw.decode("ascii")))
    except (UnicodeDecodeError, ValueError):
        raise SignatureRejected("private-key reference encoding rejected") from None


def tls_fingerprint(der_certificate: bytes) -> str:
    return hashlib.sha256(der_certificate).hexdigest()
