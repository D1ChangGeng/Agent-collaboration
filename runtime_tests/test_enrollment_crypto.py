"""Actual wheel behavior, including the upstream mixed-order regression vector.

Vector source: libsodium commit ad3004e, test/default/core_ed25519.c,
not_main_subgroup_p. No test vector is used as a production blacklist.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nacl.bindings import crypto_core_ed25519_is_valid_point
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from runtime.enrollment import EnrollmentAuthority
from runtime.errors import AcceptanceGuardFailed


@pytest.mark.parametrize("message", [b"runtime registration challenge", b"different receipt challenge"])
def test_identity_key_and_its_message_independent_forgery_are_rejected(message):
    identity = bytes.fromhex("01" + "00" * 31)
    forged = identity + bytes(32)
    assert crypto_core_ed25519_is_valid_point(identity) is False
    with pytest.raises(AcceptanceGuardFailed, match="strict Ed25519 point validation"):
        EnrollmentAuthority.verify_signature(identity.hex(), forged.hex(), message.hex())
    with pytest.raises(BadSignatureError):
        VerifyKey(identity).verify(message, forged)


def test_installed_wheel_rejects_upstream_ad3004e_mixed_order_vector():
    # https://github.com/jedisct1/libsodium/commit/ad3004e
    mixed_order = bytes.fromhex("95" + "99" * 31)
    assert crypto_core_ed25519_is_valid_point(mixed_order) is False
    with pytest.raises(AcceptanceGuardFailed, match="strict Ed25519 point validation"):
        EnrollmentAuthority.validate_public_key(mixed_order.hex())


def test_cryptography_signing_interoperates_with_strict_pynacl_verification():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    message = b"actual Ed25519 interop, no OS or Harness assertion"
    assert crypto_core_ed25519_is_valid_point(public) is True
    assert EnrollmentAuthority.validate_public_key(public.hex()) == public
    EnrollmentAuthority.verify_signature(public.hex(), key.sign(message).hex(), message.hex())
    with pytest.raises(BadSignatureError):
        EnrollmentAuthority.verify_signature(public.hex(), key.sign(message).hex(), b"different".hex())
