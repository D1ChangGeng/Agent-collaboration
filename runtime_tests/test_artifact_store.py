"""Filesystem conformance for the Linux backend, not an overall Runtime Gate."""

import hashlib
import os
import stat
import sys

import pytest
from runtime.artifacts import ArtifactError, LocalArtifactStore

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux dir_fd backend")


@pytest.mark.parametrize("unsupported", ["platform", "capabilities"])
def test_unsupported_backend_rejects_before_filesystem_writes(tmp_path, monkeypatch, unsupported):
    if unsupported == "platform":
        monkeypatch.setattr(sys, "platform", "win32")
    else:
        monkeypatch.setattr(os, "supports_dir_fd", set())

    def unexpected_write(*args, **kwargs):
        pytest.fail("unsupported backend attempted a filesystem write")

    monkeypatch.setattr(os, "mkdir", unexpected_write)
    with pytest.raises(ArtifactError, match="requires Linux"):
        LocalArtifactStore(tmp_path / "must-not-exist", "scope-a")
    assert not (tmp_path / "must-not-exist").exists()


@linux
def test_roundtrip_idempotence_and_durable_scope_binding(tmp_path):
    root = tmp_path / "cas"
    with LocalArtifactStore(root, "scope-a") as store:
        for payload in (b"", b"hello\x00world"):
            ref = store.put_bytes(payload, kind="output")
            inode = (root / ref.path).stat().st_ino
            assert store.put_bytes(payload, kind="output") == ref
            assert (root / ref.path).stat().st_ino == inode
            assert store.verify(ref) is ref
            assert store.read(ref) == payload
            assert (root / ref.path).stat().st_mode & 0o222 == 0
        with pytest.raises(AttributeError):
            store.scope_id = "scope-b"
        with pytest.raises(AttributeError):
            store.root = tmp_path / "other"
    with LocalArtifactStore(root, "scope-a") as reopened:
        assert reopened.read(ref) == payload
    with pytest.raises(ArtifactError):
        LocalArtifactStore(root, "scope-b")
    assert (root / ".scope").read_bytes() == b"scope-a"
    assert not list(root.rglob(".artifact-*"))


@linux
def test_nonempty_unbound_root_and_corrupt_scope_are_rejected(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    (root / "unclaimed").write_bytes(b"preserved")
    with pytest.raises(ArtifactError, match="nonempty"):
        LocalArtifactStore(root, "scope-a")
    assert not (root / ".scope").exists()
    assert (root / "unclaimed").read_bytes() == b"preserved"
    (root / ".scope").write_bytes(b"malformed")
    with pytest.raises(ArtifactError):
        LocalArtifactStore(root, "scope-a")
    assert (root / ".scope").read_bytes() == b"malformed"


@linux
@pytest.mark.parametrize("update", [
    {"scope_id": "scope-b"}, {"immutable": False}, {"immutable": 1},
    {"path": "../escape"}, {"path": "aa/" + "0" * 64},
    {"sha256": "G" * 64}, {"sha256": 12},
    {"size_bytes": -1}, {"size_bytes": True}, {"size_bytes": "4"},
    {"size_bytes": 3}, {"size_bytes": 5}, {"kind": "invented"},
])
def test_reference_fields_revalidated_even_after_model_copy(tmp_path, update):
    with LocalArtifactStore(tmp_path / "cas", "scope-a") as store:
        ref = store.put_bytes(b"data")
        broken = ref.model_copy(update=update)
        with pytest.raises(ArtifactError):
            store.read(broken)
        with pytest.raises(ArtifactError):
            store.verify(broken)
        with pytest.raises(ArtifactError, match="typed"):
            store.read(ref.model_dump())


@linux
def test_digest_mismatch_and_corrupt_existing_object_are_rejected(tmp_path):
    with LocalArtifactStore(tmp_path / "cas", "scope-a") as store:
        ref = store.put_bytes(b"data")
        path = store.root / ref.path
        path.chmod(0o600)
        path.write_bytes(b"evil")
        inode = path.stat().st_ino
        with pytest.raises(ArtifactError, match="digest"):
            store.read(ref)
        with pytest.raises(ArtifactError, match="corrupt"):
            store.put_bytes(b"data")
        assert path.read_bytes() == b"evil"
        assert path.stat().st_ino == inode
        assert not list(store.root.rglob(".artifact-*"))


@linux
def test_limits_and_explicit_source_authorization(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "ok").write_bytes(b"1234")
    (source / "big").write_bytes(b"12345")
    (source / "subdir").mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"abc")
    with (LocalArtifactStore(tmp_path / "deny", "s", max_bytes=4) as denied,
          pytest.raises(ArtifactError, match="authorized")):
        denied.put_file(source / "ok")
    with LocalArtifactStore(tmp_path / "cas", "s", max_bytes=4,
                            authorized_source_roots=[source]) as store:
        assert store.read(store.put_file(source / "ok")) == b"1234"
        with pytest.raises(ArtifactError, match="authorized"):
            store.put_file(outside)
        with pytest.raises(ArtifactError, match="traversal"):
            store.put_file(source / ".." / "outside")
        with pytest.raises(ArtifactError, match="max_bytes"):
            store.put_file(source / "big")
        with pytest.raises(ArtifactError, match="max_bytes"):
            store.put_bytes(b"12345")
        with pytest.raises(TypeError):
            store.put_bytes(bytearray(b"123"))
        with pytest.raises(ArtifactError, match="regular"):
            store.put_file(source / "subdir")


@linux
@pytest.mark.parametrize("mode", ["source", "artifact"])
def test_file_growth_is_bounded_after_initial_fstat(tmp_path, monkeypatch, mode):
    source = tmp_path / "source"
    source.mkdir()
    target = source / "growing"
    target.write_bytes(b"123")
    with LocalArtifactStore(tmp_path / "cas", "s", max_bytes=4,
                            authorized_source_roots=[source]) as store:
        ref = store.put_bytes(b"123")
        if mode == "artifact":
            target = store.root / ref.path
            target.chmod(0o600)
        inode = target.stat().st_ino
        real_read = os.read
        requests = []

        def growing_read(fd, count):
            if os.fstat(fd).st_ino == inode:
                requests.append(count)
                if len(requests) == 1:
                    with target.open("ab") as stream:
                        stream.write(b"456789")
            return real_read(fd, count)

        monkeypatch.setattr(os, "read", growing_read)
        with pytest.raises(ArtifactError, match="max_bytes"):
            store.put_file(target) if mode == "source" else store.read(ref)
        assert requests and max(requests) <= 5


@linux
@pytest.mark.parametrize("location", ["root", "root-parent", "source-root", "source-parent"])
def test_configured_symlink_components_are_rejected(tmp_path, location):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    configured = link if location.endswith("root") else link / "nested"
    kwargs = {"root": configured} if location.startswith("root") else {
        "root": tmp_path / "cas", "authorized_source_roots": [configured]
    }
    with pytest.raises(ArtifactError):
        LocalArtifactStore(scope_id="s", **kwargs)
    assert list(real.iterdir()) == []


@linux
def test_source_symlinks_and_nonregular_objects_are_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"do not read")
    (source / "final").symlink_to(outside / "secret")
    (source / "parent").symlink_to(outside, target_is_directory=True)
    (source / "directory").mkdir()
    os.mkfifo(source / "pipe")
    with LocalArtifactStore(tmp_path / "cas", "s", authorized_source_roots=[source]) as store:
        for name in ("final", "parent/secret", "directory", "pipe"):
            with pytest.raises(ArtifactError):
                store.put_file(source / name)


@linux
@pytest.mark.parametrize("location", ["final", "parent"])
def test_artifact_symlink_rejected_for_read_and_write(tmp_path, location):
    with LocalArtifactStore(tmp_path / "cas", "s") as store:
        ref = store.put_bytes(b"data")
        path = store.root / ref.path
        outside = tmp_path / "outside"
        if location == "final":
            outside.write_bytes(b"data")
            path.unlink()
            path.symlink_to(outside)
        else:
            path.parent.rename(outside)
            path.parent.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ArtifactError):
            store.read(ref)
        with pytest.raises(ArtifactError):
            store.put_bytes(b"data")


@linux
def test_source_parent_replaced_between_real_opens_keeps_pinned_identity(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    parent = source / "parent"
    parent.mkdir()
    (parent / "input").write_bytes(b"authorized")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "input").write_bytes(b"secret")
    moved = source / "moved"
    with LocalArtifactStore(tmp_path / "cas", "s", authorized_source_roots=[source]) as store:
        real_open = os.open

        def replace_after_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if path == "parent" and not moved.exists():
                parent.rename(moved)
                parent.symlink_to(outside, target_is_directory=True)
            return fd

        monkeypatch.setattr(os, "open", replace_after_open)
        ref = store.put_file(parent / "input")
        assert store.read(ref) == b"authorized"
        assert (outside / "input").read_bytes() == b"secret"


@linux
def test_cas_parent_replaced_between_real_opens_never_writes_symlink_target(tmp_path, monkeypatch):
    payload = b"candidate"
    digest = hashlib.sha256(payload).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    with LocalArtifactStore(tmp_path / "cas", "s") as store:
        parent = store.root / digest[:2]
        moved = store.root / "moved"
        real_open = os.open

        def replace_after_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if path == digest[:2] and not moved.exists():
                parent.rename(moved)
                parent.symlink_to(outside, target_is_directory=True)
            return fd

        monkeypatch.setattr(os, "open", replace_after_open)
        ref = store.put_bytes(payload)
        assert list(outside.iterdir()) == []
        assert (moved / digest).read_bytes() == payload
        with pytest.raises(ArtifactError):
            store.read(ref)
        parent.unlink()
        moved.rename(parent)
        assert store.read(ref) == payload


@linux
def test_root_path_replacement_after_initialization_keeps_open_root(tmp_path):
    root = tmp_path / "cas"
    outside = tmp_path / "outside"
    outside.mkdir()
    with LocalArtifactStore(root, "s") as store:
        root.rename(tmp_path / "moved")
        root.symlink_to(outside, target_is_directory=True)
        ref = store.put_bytes(b"pinned")
        assert store.read(ref) == b"pinned"
        assert list(outside.iterdir()) == []


@linux
def test_root_parent_replaced_during_initialization_uses_directory_identity(tmp_path, monkeypatch):
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = tmp_path / "moved"
    real_open = LocalArtifactStore._open_child_directory

    def replace_after_open(parent, name, *, create):
        fd = real_open(parent, name, create=create)
        if name == "anchor" and not moved.exists():
            anchor.rename(moved)
            anchor.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(LocalArtifactStore, "_open_child_directory", staticmethod(replace_after_open))
    with LocalArtifactStore(anchor / "cas", "s") as store:
        ref = store.put_bytes(b"pinned during initialization")
        assert store.read(ref) == b"pinned during initialization"
        assert list(outside.iterdir()) == []
        assert (moved / "cas" / ref.path).read_bytes() == b"pinned during initialization"


@linux
def test_fsync_order_and_failed_write_cleanup(tmp_path, monkeypatch):
    with LocalArtifactStore(tmp_path / "cas", "s") as store:
        real_sync, real_link = os.fsync, os.link
        events = []

        def sync(fd):
            events.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
            return real_sync(fd)

        def link(*args, **kwargs):
            events.append("link")
            return real_link(*args, **kwargs)

        monkeypatch.setattr(os, "fsync", sync)
        monkeypatch.setattr(os, "link", link)
        store.put_bytes(b"durable")
        assert events.index("file") < events.index("link")
        assert "directory" in events[events.index("link") + 1:]
        descriptors_before = len(os.listdir("/proc/self/fd"))

        def fail_file_sync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("injected disk failure")
            return real_sync(fd)

        monkeypatch.setattr(os, "fsync", fail_file_sync)
        with pytest.raises(OSError, match="disk failure"):
            store.put_bytes(b"failed")
        assert not list(store.root.rglob(".artifact-*"))
        assert len(os.listdir("/proc/self/fd")) == descriptors_before


@linux
def test_close_and_failed_initialization_release_handles(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(ArtifactError):
        LocalArtifactStore(tmp_path / "not-created", "s",
                           authorized_source_roots=[source, tmp_path / "missing"])
    assert not (tmp_path / "not-created").exists()
    assert len(os.listdir("/proc/self/fd")) == before
    store = LocalArtifactStore(tmp_path / "cas", "s", authorized_source_roots=[source])
    ref = store.put_bytes(b"test")
    store.close()
    store.close()
    assert len(os.listdir("/proc/self/fd")) == before
    for operation in (lambda: store.read(ref), lambda: store.verify(ref),
                      lambda: store.put_bytes(b"new"), lambda: store.put_file(source / "x"),
                      lambda: store.__enter__()):
        with pytest.raises(ArtifactError, match="closed"):
            operation()
