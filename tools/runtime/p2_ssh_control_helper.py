"""Answer one P2 control challenge through an actual SSH/SCP session."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from tools.runtime.p2_control_proof import answer


def run(arguments) -> dict:
    transcript = []

    def command(argv, *, check=True):
        started = datetime.now(UTC).isoformat()
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=15, check=False,
        )
        transcript.append({
            "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
            "started_at": started, "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        })
        if check and result.returncode != 0:
            raise RuntimeError("SSH control command failed")
        return result

    with tempfile.TemporaryDirectory(prefix="acs-p2-control-") as temporary:
        challenge = Path(temporary) / "challenge.json"
        proof = Path(temporary) / "proof.json"
        deadline = time.monotonic() + arguments.timeout_seconds
        while time.monotonic() < deadline:
            found = command([
                arguments.ssh, arguments.target, "test", "-f",
                arguments.remote_challenge,
            ], check=False)
            if found.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("SSH control challenge was not observed")
        command([
            arguments.scp, f"{arguments.target}:{arguments.remote_challenge}",
            str(challenge),
        ])
        value = answer(
            challenge, arguments.key, proof,
            host=arguments.host, session=arguments.session,
        )
        command([
            arguments.scp, str(proof),
            f"{arguments.target}:{arguments.remote_proof}",
        ])
        command([
            arguments.ssh, arguments.target, "chmod", "600", arguments.remote_proof,
        ])
        consumed = command([
            arguments.ssh, arguments.target, "test", "-f", arguments.remote_proof,
        ], check=False)
    evidence = {
        "schema_version": "acs-p2-ssh-control-evidence/1",
        "target": arguments.target, "host": arguments.host,
        "session": arguments.session, "observed_at": datetime.now(UTC).isoformat(),
        "proof_public_key": value["body"]["public_key"],
        "challenge_run_id": value["body"]["run_id"],
        "transcript": transcript,
        "status": "answered" if consumed.returncode == 0 else "consumed_by_receiver",
    }
    arguments.evidence.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    print(json.dumps(evidence, sort_keys=True))
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--remote-challenge", required=True)
    parser.add_argument("--remote-proof", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--host", required=True); parser.add_argument("--session", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--ssh", default="ssh"); parser.add_argument("--scp", default="scp")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
