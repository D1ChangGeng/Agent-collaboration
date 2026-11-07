"""Run local cross-Harness regressions against an explicitly isolated test database.

Credentials stay in the child environment. This helper never selects a deployment
DSN, changes a running service, or sends a message to an existing ACS contact.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE = "acs_communication_test"
TEST_CONTAINER = "acs-communication-test-20261031"


def isolated_environment(container: str | None) -> dict[str, str]:
    environment = dict(os.environ)
    dsn = environment.get("ACS_COMMUNICATION_TEST_DSN")
    if container:
        if container != TEST_CONTAINER:
            raise ValueError("only the explicitly named ACS test container is admitted")
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "docker", "inspect", container],
            check=True, capture_output=True, timeout=30,
        )
        info = json.loads(result.stdout)[0]
        values = dict(item.split("=", 1) for item in info["Config"]["Env"] if "=" in item)
        if values.get("POSTGRES_DB") != TEST_DATABASE:
            raise ValueError("container is not the isolated ACS database")
        ports = info["NetworkSettings"]["Ports"]["5432/tcp"]
        if len(ports) != 1 or ports[0]["HostIp"] != "127.0.0.1":
            raise ValueError("test database must have one loopback-only port")
        user = quote(values["POSTGRES_USER"], safe="")
        password = quote(values["POSTGRES_PASSWORD"], safe="")
        dsn = (
            f"postgresql://{user}:{password}@127.0.0.1:"
            f"{int(ports[0]['HostPort'])}/{TEST_DATABASE}?connect_timeout=5"
        )
    if dsn:
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(dsn).get("dbname") != TEST_DATABASE:
            raise ValueError("deployment databases are forbidden")
        environment["ACS_COMMUNICATION_TEST_DSN"] = dsn
        environment["ACS_P1_DSN"] = dsn
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-container", choices=(TEST_CONTAINER,))
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args()
    try:
        environment = isolated_environment(args.test_container)
    except (KeyError, ValueError, OSError, subprocess.SubprocessError):
        print("isolated_test_environment_unavailable", file=sys.stderr)
        return 2
    args.log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", "-ra", "--tb=short", *args.tests]
    with args.log.open("w", encoding="utf-8") as output:
        output.write(json.dumps({"command": command, "database": TEST_DATABASE if
            "ACS_COMMUNICATION_TEST_DSN" in environment else "not-configured"}) + "\n")
        output.flush()
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, check=False)
    print(args.log.read_text(encoding="utf-8"))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
