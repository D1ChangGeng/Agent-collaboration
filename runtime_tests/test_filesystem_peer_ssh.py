"""Actual OpenSSH forced-command reads use the committed ACS collaborator binding.

Set ACS_TEST_SSHD to an installed native sshd. This optional transport test does
not claim that a public SSH service or a production tunnel has been qualified.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_identity_root_management import accepted
from runtime_tests.test_identity_root_management import owner_client as owner_client_fixture

comm = comm_fixture
owner_client = owner_client_fixture
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ssh_key_directory():
    with tempfile.TemporaryDirectory(prefix=".acs-ssh-test-", dir=Path.home()) as directory:
        yield Path(directory)


@pytest.mark.skipif(os.name != "posix", reason="native sshd transport requires POSIX")
def test_native_ssh_current_management_and_live_revocation(comm, owner_client, tmp_path, ssh_key_directory):
    binary = os.environ.get("ACS_TEST_SSHD") or shutil.which("sshd")
    if not binary:
        pytest.skip("native sshd unavailable: set ACS_TEST_SSHD")
    directory = tmp_path / "management"
    directory.mkdir()
    document = directory / "AGENTS.md"
    document.write_bytes(b"Owner current instructions\n")
    accepted(owner_client, "configure_root", project_id="project-alpha", changes={
        "management": {"mode": "current_files", "machine_id": "local", "path": str(directory)},
        "instruction_paths": ["AGENTS.md"], "knowledge_index_paths": []})
    binding = accepted(owner_client, "configure_team", project_id="project-alpha", prepare_native=False,
        members=[{"agent_slot_id": "ssh-reader", "principal_ref": "agent:ssh-reader", "role": "engineer"}])["caller_bindings"][0]
    token = "test-only-ssh-reader"
    context = replace(comm.authority.context, principal_ref=binding["principal_ref"], grant_ref=binding["grant_ref"],
        agent_slot_id=binding["agent_slot_id"], trusted_client=False, credential_hash=hashlib.sha256(token.encode()).hexdigest())
    for name, content in (("dsn", comm.dsn), ("credential", token)):
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o600)
    config = tmp_path / "surface.json"
    config.write_text(json.dumps({"access_mode": "owner", "context": asdict(context),
        "dsn_ref": {"kind": "file", "name": str(tmp_path / "dsn")},
        "credential_ref": {"kind": "file", "name": str(tmp_path / "credential")}, "delivery_maintenance": "external"}))
    config.chmod(0o600)
    for name in ("host", "reader", "wrong-reader"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(ssh_key_directory / name)],
                       capture_output=True, check=True, timeout=10)
    keys = ssh_key_directory / "authorized_keys"
    keys.write_text("restrict " + (ssh_key_directory / "reader.pub").read_text())
    keys.chmod(0o600)
    arguments = ["--config", str(config), "--catalog", str(ROOT / "docs/runtime/p2-mcp-tool-contract.json"),
        "--project-id", "project-alpha", "--profile", "engineer", "--machine-id", "owner-source",
        "--cwd", str(directory), "--read-root", str(directory)]
    wrapper = tmp_path / "peer.py"
    wrapper.write_text("import sys\nsys.dont_write_bytecode=True\nsys.path.insert(0," + repr(str(ROOT)) + ")\n"
        "from runtime.filesystem_peer_entry import main\nraise SystemExit(main(" + repr(arguments) + "))\n")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = tmp_path / "sshd_config"
    server.write_text("\n".join(["Port " + str(port), "ListenAddress 127.0.0.1", "HostKey " + str(ssh_key_directory / "host"),
        "AuthorizedKeysFile " + str(keys), "PidFile " + str(tmp_path / "sshd.pid"), "UsePAM no",
        "PasswordAuthentication no", "KbdInteractiveAuthentication no", "AuthenticationMethods publickey",
        "PermitRootLogin no", "StrictModes yes", "PermitTTY no", "DisableForwarding yes",
        "ForceCommand " + shlex.join([sys.executable, str(wrapper)]), ""]))
    subprocess.run([binary, "-t", "-f", str(server)], capture_output=True, check=True, timeout=10)
    known = tmp_path / "known_hosts"
    known.write_text("[127.0.0.1]:" + str(port) + " " + (ssh_key_directory / "host.pub").read_text())
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
        "UserKnownHostsFile=" + str(known), "-o", "ConnectTimeout=5", "-i", str(ssh_key_directory / "reader"),
        "-p", str(port), "127.0.0.1", "acs-filesystem"]

    def call(operation, path):
        result = subprocess.run(command, input=json.dumps({"machine_id": "owner-source", "operation": operation,
            "arguments": {"path": str(path), "cwd": str(directory)}}), capture_output=True, text=True, timeout=25, check=False)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    with (tmp_path / "sshd.log").open("w") as errors:
        process = subprocess.Popen([binary, "-D", "-e", "-f", str(server)], stdout=subprocess.DEVNULL, stderr=errors)
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.02)
            first = call("read_file", document)
            assert first["ok"] and first["data"]["content"] == "Owner current instructions\n"
            document.write_bytes(b"Owner changed instructions\n")
            assert call("read_file", document)["data"]["content"] == "Owner changed instructions\n"
            assert call("write_file", document)["error"]["code"] == "profile_denied"
            assert call("read_file", tmp_path / "credential")["error"]["code"] == "profile_denied"
            wrong = list(command)
            wrong[wrong.index(str(ssh_key_directory / "reader"))] = str(ssh_key_directory / "wrong-reader")
            assert subprocess.run(wrong, input="{}", capture_output=True, text=True, timeout=10, check=False).returncode != 0
            with comm.authority._connect() as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (binding["grant_ref"],))
            denied = call("read_file", document)
            assert not denied["ok"] and denied["error"]["code"] == "revoked"
            assert document.read_bytes() == b"Owner changed instructions\n"
            assert all(not driver.calls for driver in comm.drivers.values())
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="native sshd supervision requires POSIX")
def test_native_file_peer_supervisor_recovers_its_owned_child(ssh_key_directory):
    binary = os.environ.get("ACS_TEST_SSHD") or shutil.which("sshd")
    if not binary:
        pytest.skip("native sshd unavailable: set ACS_TEST_SSHD")
    root = ssh_key_directory
    native = Path(binary)
    binary = root / "sshd"
    shutil.copyfile(native, binary)
    binary.chmod(0o700)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / "host")],
                   capture_output=True, check=True, timeout=10)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = root / "sshd_config"
    config.write_text("\n".join(["Port " + str(port), "ListenAddress 127.0.0.1", "HostKey " + str(root / "host"),
        "AuthorizedKeysFile /dev/null", "PidFile " + str(root / "sshd.pid"), "UsePAM no",
        "PasswordAuthentication no", "KbdInteractiveAuthentication no", "PermitTTY no",
        "DisableForwarding yes", "ForceCommand /usr/bin/true", ""]))
    config.chmod(0o600)
    profile = root / "file-peer.json"
    data = {"schema_version": "acs-read-only-file-peer-startup/1", "root": str(root), "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "config_file": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}
    profile.write_text(json.dumps(data))
    profile.chmod(0o600)
    specification = importlib.util.spec_from_file_location("acs_native_startup_probe", ROOT / "scripts/acs_startup.py")
    startup = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(startup)
    supervisor = subprocess.Popen([sys.executable, str(ROOT / "scripts/acs_startup.py"), "--supervise-file-peer", str(profile)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def owned_child(previous=None):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            assert supervisor.poll() is None, "owned supervisor stopped"
            pid = startup.file_peer_pid(data)
            if pid is not None and pid != previous:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1) as stream:
                        assert stream.recv(128).startswith(b"SSH-")
                    return pid
                except OSError:
                    pass
            time.sleep(0.05)
        raise AssertionError("owned SSH child did not recover")

    try:
        first = owned_child()
        os.kill(first, signal.SIGTERM)
        second = owned_child(first)
        assert second != first
    finally:
        supervisor.terminate()
        supervisor.wait(timeout=5)
        pid = startup.file_peer_pid(data)
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
