"""Stage and atomically provision an owner-private receiver wheel installation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from runtime.receiver_install import (
    INSTALL_MANIFEST,
    record_hash,
    verify_wheel_archive,
)


def _private_directory(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError("receiver install parent path contains a symlink")
    info = path.stat(follow_symlinks=False)
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("receiver install parent must be owner mode 0700 without symlinks")


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _harden_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ValueError("receiver installation contains a symlink")
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)
        else:
            raise ValueError("receiver installation contains an unsupported file type")


def provision(wheel: str | Path, destination: str | Path, *, python: str = sys.executable,
              pip_python: str = sys.executable) -> dict:
    if os.name != "posix" or os.geteuid() == 0:
        raise ValueError("receiver provisioning requires a non-root POSIX user")
    wheel = Path(wheel).absolute()
    destination = Path(destination).absolute()
    parent = destination.parent
    _private_directory(parent)
    if destination.exists() or destination.is_symlink():
        raise ValueError("receiver install destination already exists")
    wheel_files = verify_wheel_archive(wheel)
    stage = parent / f".receiver-stage-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    adopted = False
    try:
        report_path = stage / "pip-install-report.json"
        installed = subprocess.run(
            [pip_python, "-m", "pip", "--python", python, "install",
             "--ignore-installed", "--no-deps", "--prefix", str(stage),
             "--report", str(report_path), str(wheel)],
            check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        installs = report.get("install") if isinstance(report, dict) else None
        if (not isinstance(installs, list) or len(installs) != 1
                or installs[0].get("metadata", {}).get("name") != "agent-collaboration-runtime"):
            raise ValueError("receiver provision pip report differs from the requested wheel")
        if "Successfully installed" not in installed.stdout:
            raise ValueError("receiver provision pip did not confirm a staged installation")
        report_path.unlink()
        sites = list(stage.glob("lib/python*/site-packages"))
        if len(sites) != 1:
            raise ValueError("receiver provision did not create one site-packages directory")
        site = sites[0]
        launcher = stage / "bin" / "acs-receiver"
        provisioner = stage / "bin" / "acs-receiver-provision"
        launcher.parent.mkdir(mode=0o700, exist_ok=True)
        final_site = destination / site.relative_to(stage)
        interpreter = Path(python).absolute()
        for script, module in ((launcher, "runtime.receiver_entry"),
                               (provisioner, "runtime.receiver_provision")):
            script.write_text(
                f"#!{interpreter}\nimport sys\nsys.dont_write_bytecode=True\n"
                f"sys.path.insert(0, {str(final_site)!r})\n"
                f"from {module} import main\nraise SystemExit(main())\n",
                encoding="utf-8", newline="\n",
            )
            script.chmod(0o700)
        records = list(site.glob("*.dist-info/RECORD"))
        if len(records) != 1:
            raise ValueError("receiver provision has no unique RECORD")
        record_path = records[0]
        record_relative = str(record_path.relative_to(site)).replace("\\", "/")
        launcher_relative = os.path.relpath(launcher, site).replace("\\", "/")
        provisioner_relative = os.path.relpath(provisioner, site).replace("\\", "/")
        rows = list(csv.reader(io.StringIO(record_path.read_text(encoding="utf-8"))))
        updated = []
        for relative, encoded, size in rows:
            path = (site / relative).resolve()
            if relative == record_relative:
                continue
            if relative.endswith(".pyc") and not encoded:
                if path.exists():
                    path.unlink()
                continue
            if relative in {launcher_relative, provisioner_relative}:
                continue
            if not encoded or not size:
                raise ValueError("receiver provision found an unhashed RECORD entry")
            updated.append([relative, encoded, size])
        launcher_data = launcher.read_bytes()
        updated.append([launcher_relative, record_hash(launcher_data), str(len(launcher_data))])
        provisioner_data = provisioner.read_bytes()
        updated.append([
            provisioner_relative, record_hash(provisioner_data), str(len(provisioner_data)),
        ])
        updated.append([record_relative, "", ""])
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows(sorted(updated))
        record_path.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
        _harden_tree(stage)
        launcher.chmod(0o700)
        provisioner.chmod(0o700)
        record_sha = hashlib.sha256(record_path.read_bytes()).hexdigest()
        files = {}
        for relative, encoded, size in updated:
            if relative == record_relative:
                continue
            path = (site / relative).resolve()
            data = path.read_bytes()
            if record_hash(data) != encoded or str(len(data)) != size:
                raise ValueError("receiver provision RECORD rewrite did not verify")
            files[relative] = hashlib.sha256(data).hexdigest()
        if any(relative not in files for relative in wheel_files):
            raise ValueError("receiver provision omitted wheel package content")
        manifest = {
            "schema_version": "acs-receiver-install/1",
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "record_sha256": record_sha,
            "files": files,
            "site_packages": str(site.relative_to(stage)),
            "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            "provisioner_sha256": hashlib.sha256(provisioner.read_bytes()).hexdigest(),
            "interpreter_path": str(interpreter),
            "interpreter_path_sha256": hashlib.sha256(str(interpreter).encode()).hexdigest(),
            "interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        }
        manifest_path = stage / INSTALL_MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8", newline="\n",
        )
        manifest_path.chmod(0o600)
        for path in stage.rglob("*"):
            if path.is_file():
                with path.open("rb") as source:
                    os.fsync(source.fileno())
        _fsync(stage)
        os.replace(stage, destination)
        adopted = True
        _fsync(parent)
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}
        completed = subprocess.run(
            [destination / "bin" / "acs-receiver", "--verify-install"],
            cwd=destination, env=environment, capture_output=True, text=True,
            check=True, timeout=30,
        )
        verified = json.loads(completed.stdout)
        return {"destination": str(destination), "manifest": manifest,
                "postflight": verified}
    except BaseException:
        source = destination if adopted and destination.exists() else stage
        if source.exists():
            failed = parent / f".receiver-failed-{uuid.uuid4().hex}"
            os.replace(source, failed)
            _fsync(parent)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog="acs-receiver-provision")
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--pip-python", default=sys.executable)
    arguments = parser.parse_args(argv)
    result = provision(
        arguments.wheel, arguments.destination,
        python=arguments.python, pip_python=arguments.pip_python,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
