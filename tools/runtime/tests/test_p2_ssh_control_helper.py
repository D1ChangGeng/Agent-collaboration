from argparse import Namespace
from pathlib import Path

from nacl.signing import SigningKey

from tools.runtime import p2_ssh_control_helper as helper


def test_helper_uses_ssh_and_scp_for_challenge_round_trip(tmp_path, monkeypatch):
    key = SigningKey.generate(); key_path = tmp_path / "key"
    key_path.write_text(key.encode().hex()); key_path.chmod(0o600)
    calls = []

    class Result:
        returncode = 0; stdout = ""; stderr = ""

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "scp" and argv[1].endswith(":/challenge"):
            from tools.runtime.p2_control_proof import issue
            issue(Path(argv[2]), run_id="run", expected_host="windows",
                  expected_session="session")
        return Result()

    monkeypatch.setattr(helper.subprocess, "run", run)
    args = Namespace(
        target="host", remote_challenge="/challenge", remote_proof="/proof",
        key=key_path, host="windows", session="session",
        evidence=tmp_path / "evidence.json", timeout_seconds=2,
        ssh="ssh", scp="scp",
    )
    helper.run(args)

    assert [call[0] for call in calls] == ["ssh", "scp", "scp", "ssh", "ssh"]
    assert calls[-2][-3:] == ["chmod", "600", "/proof"]
