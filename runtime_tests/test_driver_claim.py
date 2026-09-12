"""Real kernel claim tests; subprocesses never execute a model or native turn."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.codex_driver import DriverJournal, DriverRejected


def competitor(path):
    script = """
import sys
from runtime.codex_driver import DriverJournal,DriverRejected
journal=DriverJournal(sys.argv[1])
try: fd=journal.claim('binding')
except DriverRejected: print('blocked')
else:
 token=journal.claim_token('binding',fd)
 journal.release_claim(token)
 print('acquired')
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                            capture_output=True, timeout=10, check=True)
    return result.stdout.decode().strip()


def test_kernel_reservation_competition_and_controlled_release(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = DriverJournal(path)
    descriptor = journal.claim("binding")
    token = journal.claim_token("binding", descriptor)
    try:
        assert competitor(path) == "blocked"
        journal.validate_claim(token, "binding", descriptor)
    finally:
        journal.release_claim(token)
    assert competitor(path) == "acquired"
    assert not journal._claims


def test_same_fd_same_inode_reopen_loses_continuity_but_not_private_reservation(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = DriverJournal(path)
    descriptor = journal.claim("binding")
    token = journal.claim_token("binding", descriptor)
    before = os.fstat(descriptor)
    os.close(descriptor)
    reopened = os.open(token.path, os.O_RDONLY)
    if reopened != descriptor:
        os.dup2(reopened, descriptor)
        os.close(reopened)
    try:
        after = os.fstat(descriptor)
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        assert competitor(path) == "blocked"
        with pytest.raises(DriverRejected, match="continuity"):
            journal.validate_claim(token, "binding", descriptor)
    finally:
        journal.release_claim(token)
        os.close(descriptor)  # The reused descriptor belongs to this test, not the token.
    assert competitor(path) == "acquired"


@pytest.mark.skipif(os.name != "posix", reason="Linux actual flock-unlock proof")
def test_another_owner_cannot_supply_the_original_descriptors_lock_proof(tmp_path):
    import fcntl

    journal = DriverJournal(tmp_path / "journal.sqlite")
    descriptor = journal.claim("binding")
    token = journal.claim_token("binding", descriptor)
    fcntl.flock(token._owner_fd, fcntl.LOCK_UN)  # Explicit internal fault injection.
    rival = DriverJournal(journal.path)
    rival_fd = rival.claim("binding")
    rival_token = rival.claim_token("binding", rival_fd)
    try:
        rival.validate_claim(rival_token, "binding", rival_fd)
        with pytest.raises(DriverRejected, match="continuity"):
            journal.validate_claim(token, "binding", descriptor)
    finally:
        rival.release_claim(rival_token)
        journal.release_claim(token)


@pytest.mark.skipif(os.name != "nt", reason="Windows immutable share reservation")
def test_public_byte_unlock_cannot_remove_private_windows_reservation(tmp_path):
    import msvcrt

    journal = DriverJournal(tmp_path / "journal.sqlite")
    descriptor = journal.claim("binding")
    token = journal.claim_token("binding", descriptor)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        journal.validate_claim(token, "binding", descriptor)
        assert competitor(journal.path) == "blocked"
    finally:
        journal.release_claim(token)


@pytest.mark.parametrize("driver_kind", ["codex", "opencode"])
def test_driver_constructor_token_failure_releases_kernel_ownership(tmp_path, monkeypatch, driver_kind):
    from runtime.codex_driver import BindingIdentity, CodexAppServerDriver
    from runtime.opencode_driver import OpenCodeNativeDriver

    journal = DriverJournal(tmp_path / "journal.sqlite")
    def fail(*args):
        raise RuntimeError("token lookup failed")
    monkeypatch.setattr(journal, "claim_token", fail)
    driver_type = CodexAppServerDriver if driver_kind == "codex" else OpenCodeNativeDriver
    with pytest.raises(RuntimeError, match="token lookup failed"):
        driver_type("binding", None, journal, identity=BindingIdentity("node", "boot", "runtime", "attempt", "slot", 1),
                    check_current=lambda *args: None)
    assert not journal._claims
    assert competitor(journal.path) == "acquired"


def test_partial_claim_validation_failure_closes_all_allocated_handles(tmp_path, monkeypatch):
    from runtime.driver_claim import ClaimRejected, KernelClaim

    journal = DriverJournal(tmp_path / "journal.sqlite")
    allocated = []
    def fail(self, descriptor):
        allocated.extend([self._owner_fd, self._owner_witness, self.public_fd, self._public_witness])
        raise ClaimRejected("injected proof unavailable")
    with monkeypatch.context() as fault:
        fault.setattr(KernelClaim, "validate", fail)
        with pytest.raises(DriverRejected, match="kernel ownership"):
            journal.claim_ownership("binding")
    assert not journal._claims
    for descriptor in allocated:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert competitor(journal.path) == "acquired"


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner/mode admission")
@pytest.mark.parametrize("mutation", ["parent_mode", "file_mode", "parent_link", "file_link"])
def test_private_claim_path_is_enforced(tmp_path, mutation):
    from runtime.driver_claim import ClaimRejected, KernelClaim

    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    path = parent / "claim.lock"
    path.touch(mode=0o600)
    if mutation == "parent_mode":
        parent.chmod(0o770)
    elif mutation == "file_mode":
        path.chmod(0o640)
    elif mutation == "parent_link":
        link = tmp_path / "linked"
        link.symlink_to(parent, target_is_directory=True)
        path = link / path.name
    else:
        link = parent / "linked.lock"
        link.symlink_to(path)
        path = link
    with pytest.raises((ClaimRejected, OSError)):
        KernelClaim(path, "binding")


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner uid admission")
def test_wrong_owner_uid_rejected(tmp_path, monkeypatch):
    from runtime.driver_claim import ClaimRejected, KernelClaim

    with monkeypatch.context() as fault:
        fault.setattr(os, "geteuid", lambda: os.getuid() + 1)
        with pytest.raises(ClaimRejected, match="owner uid"):
            KernelClaim(tmp_path / "claim.lock", "binding")


@pytest.mark.skipif(os.name != "posix", reason="POSIX continuous file/parent admission")
@pytest.mark.parametrize("target", ["parent", "file"])
def test_permission_change_invalidates_existing_claim(tmp_path, target):
    journal = DriverJournal(tmp_path / "journal.sqlite")
    descriptor, token = journal.claim_ownership("binding")
    path = tmp_path if target == "parent" else Path(token.path)
    original = path.stat().st_mode & 0o777
    path.chmod(0o770 if target == "parent" else 0o640)
    try:
        with pytest.raises(DriverRejected, match="continuity"):
            journal.validate_claim(token, "binding", descriptor)
    finally:
        path.chmod(original)
        journal.release_claim(token)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse component admission")
def test_windows_parent_reparse_attribute_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from runtime.driver_claim import ClaimRejected, KernelClaim

    original = Path.lstat
    def reparse(path):
        info = original(path)
        if path == tmp_path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ClaimRejected, match="reparse"):
        KernelClaim(tmp_path / "claim.lock", "binding")
