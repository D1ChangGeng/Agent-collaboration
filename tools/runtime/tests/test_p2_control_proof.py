import pytest
from nacl.signing import SigningKey

from runtime.receiver_crypto import public_key
from tools.runtime.p2_control_proof import answer, issue, validate


def test_signed_control_proof_is_one_use(tmp_path):
    challenge, proof, key_path = (
        tmp_path / "challenge.json", tmp_path / "proof.json", tmp_path / "control.seed",
    )
    key = SigningKey.generate()
    key_path.write_text(key.encode().hex()); key_path.chmod(0o600)
    issue(challenge, run_id="run", expected_host="windows-local",
          expected_session="ssh-control-1")
    answer(challenge, key_path, proof, host="windows-local", session="ssh-control-1")

    result = validate(
        challenge, proof, expected_public_key=public_key(key),
        expected_host="windows-local", expected_session="ssh-control-1",
    )

    assert result["verified"] and not proof.exists()
    with pytest.raises(ValueError, match="not fresh"):
        issue(challenge, run_id="run", expected_host="windows-local",
              expected_session="ssh-control-1")


def test_copied_signed_proof_cannot_reconsume_persistent_challenge(tmp_path):
    challenge, proof, key_path = (tmp_path / "challenge.json", tmp_path / "proof.json", tmp_path / "control.seed")
    key = SigningKey.generate()
    key_path.write_text(key.encode().hex())
    key_path.chmod(0o600)
    issue(challenge, run_id="run", expected_host="owner", expected_session="session")
    answer(challenge, key_path, proof, host="owner", session="session")
    original = proof.read_bytes()
    kwargs = {"expected_public_key": public_key(key), "expected_host": "owner", "expected_session": "session"}
    validate(challenge, proof, **kwargs)
    proof.write_bytes(original)
    proof.chmod(0o600)
    with pytest.raises(ValueError, match="already been consumed"):
        validate(challenge, proof, **kwargs)
