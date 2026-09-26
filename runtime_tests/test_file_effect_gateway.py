"""Real temporary filesystem tests; authority is an explicit test double, not PG."""

import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from runtime.effects import LocalFileEffectGateway
from runtime.errors import EffectUnavailable, FencingRejected

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux filesystem backend")


class AuthorityDouble:
    def __init__(self):
        self.generation = 1
        self.allowed = True
        self.checks = 0
        self.work_item_id = "work-item"
        self.history_calls = []

    @contextmanager
    def hold_fence(self, lease, resource, generation, token, **owner):
        def check():
            self.checks += 1
            if (
                not self.allowed
                or generation != self.generation
                or lease != f"lease-{generation}"
                or token != f"token-{generation}"
                or owner["grant_ref"] != f"grant-{generation}"
                or owner["caller"].grant_ref != owner["grant_ref"]
            ):
                raise FencingRejected(resource)

        check()
        yield {
            "check_current": check,
            "work_item_id": self.work_item_id,
            "authority_id": "authority",
        }

    def verify_historical_readback(self, *args, **kwargs):
        self.history_calls.append((args, kwargs))
        if kwargs.get("permission") != "effect.read":
            raise FencingRejected(args[1])
        if kwargs["grant_ref"] != "reader" or kwargs["caller"].grant_ref != "reader":
            raise FencingRejected(args[1])


def owner(generation=1):
    grant = f"grant-{generation}"
    return {
        "caller": SimpleNamespace(
            principal_ref=f"producer-{generation}",
            tenant_id="tenant",
            authority_id="authority",
            grant_ref=grant,
        ),
        "attempt_id": f"attempt-{generation}",
        "runtime_id": f"runtime-{generation}",
        "scope_id": "scope-a",
        "grant_ref": grant,
        "authority_incarnation": "incarnation",
    }


def write(gateway, operation="op-1", payload=b"new", generation=1, **changes):
    kwargs = owner(generation)
    kwargs.update(changes)
    return gateway.write(
        f"lease-{generation}",
        "resource",
        generation,
        f"token-{generation}",
        "nested/out",
        payload,
        operation_id=operation,
        **kwargs,
    )


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    authority = AuthorityDouble()
    with LocalFileEffectGateway(
        authority, root, scope_id="scope-a", resource_paths={"resource": "nested/out"}
    ) as gateway:
        yield authority, gateway


@pytest.mark.parametrize("mode", ["platform", "capability"])
def test_unsupported_before_writes(tmp_path, monkeypatch, mode):
    if mode == "platform":
        monkeypatch.setattr(sys, "platform", "win32")
    else:
        monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(ValueError, match="requires Linux"):
        LocalFileEffectGateway(None, tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


@linux
def test_successive_operations_and_recorded_replay(fixture):
    authority, gateway = fixture
    first = write(gateway)
    inode = (gateway.root / "nested/out").stat().st_ino
    assert write(gateway) == first
    assert (gateway.root / "nested/out").stat().st_ino == inode
    with pytest.raises(EffectUnavailable, match="conflict"):
        write(gateway, payload=b"different")
    authority.generation = 2
    second = write(gateway, "op-2", b"second", 2)
    assert second["sha256"] == hashlib.sha256(b"second").hexdigest()
    assert (gateway.root / "nested/out").read_bytes() == b"second"
    assert len(list((gateway.root / gateway.MARKER_DIR / "operations").glob("*.completed"))) == 2
    # Current owner can retrieve the original receipt without rewriting history/target.
    assert (
        gateway.resume(
            "lease-2", "resource", 2, "token-2", "nested/out", operation_id="op-1", **owner(2)
        )
        == first
    )
    assert (gateway.root / "nested/out").read_bytes() == b"second"


@linux
@pytest.mark.parametrize("stage", ["before", "after"])
def test_prepared_resume_distinguishes_unwritten_and_written(fixture, monkeypatch, stage):
    authority, gateway = fixture
    target = gateway.root / "nested/out"
    target.write_bytes(b"old")
    real_replace = os.replace
    effects = []
    fail = True

    def crash(source, destination, **kwargs):
        nonlocal fail
        if destination == "out":
            if fail and stage == "before":
                fail = False
                raise OSError("crash before effect")
            effects.append(destination)
            real_replace(source, destination, **kwargs)
            if fail:
                fail = False
                raise OSError("effect completed, acknowledgement lost")
            return None
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(EffectUnavailable):
        write(gateway)
    assert target.read_bytes() == (b"old" if stage == "before" else b"new")
    if stage == "after":
        observation = gateway.readback(
            "lease-1",
            "resource",
            1,
            "token-1",
            "nested/out",
            expected_operation_id="op-1",
            **owner(),
        )
        assert observation["completion_state"] == "prepared"
        assert observation["completion_sha256"] is None
    authority.generation = 2
    with pytest.raises(FencingRejected):
        write(gateway)
    result = gateway.reconcile(
        "lease-2", "resource", 2, "token-2", "nested/out", operation_id="op-1", **owner(2)
    )
    assert result["status"] == "verified"
    assert effects == ["out"]
    assert target.read_bytes() == b"new"
    key = hashlib.sha256(b"op-1").hexdigest()
    intent = json.loads(
        (gateway.root / gateway.MARKER_DIR / "operations" / (key + ".intent")).read_text()
    )
    assert intent["body"]["lease_id"] == "lease-1"
    assert intent["body"]["principal_ref"] == "producer-1"
    completed = json.loads(
        (gateway.root / gateway.MARKER_DIR / "operations" / (key + ".completed")).read_text()
    )
    assert completed["body"]["completed_by"]["principal_ref"] == "producer-2"
    assert completed["body"]["completion_basis"] == (
        "applied_now" if stage == "before" else "observed_target"
    )


@linux
def test_lost_current_pointer_update_is_repaired_without_effect(fixture, monkeypatch):
    _, gateway = fixture
    real_replace = os.replace
    pointer_updates = 0
    effect_count = 0

    def crash(source, destination, **kwargs):
        nonlocal pointer_updates, effect_count
        if destination.endswith(".json"):
            pointer_updates += 1
            if pointer_updates == 2:
                raise OSError("completion pointer write lost")
        if destination == "out":
            effect_count += 1
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(EffectUnavailable):
        write(gateway)
    assert write(gateway)["status"] == "verified"
    assert effect_count == 1
    assert write(gateway, "op-2", b"second")["status"] == "verified"


@linux
def test_conflicting_bytes_do_not_resume_blindly(fixture, monkeypatch):
    _, gateway = fixture
    real_replace = os.replace

    def crash(source, destination, **kwargs):
        if destination == "out":
            raise OSError("before target")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(EffectUnavailable):
        write(gateway)
    (gateway.root / "nested/out").write_bytes(b"unexpected")
    result = gateway.reconcile(
        "lease-1", "resource", 1, "token-1", "nested/out", operation_id="op-1", **owner()
    )
    assert result["status"] == "uncertain" and result["reexecute"] is False
    assert (gateway.root / "nested/out").read_bytes() == b"unexpected"


@linux
def test_history_uses_current_read_grant_and_original_operation_identity(fixture):
    authority, gateway = fixture
    write(gateway)
    authority.allowed = False
    reader = SimpleNamespace(grant_ref="reader")
    result = gateway.reconcile(
        "lease-1",
        "resource",
        1,
        "token-1",
        "nested/out",
        operation_id="op-1",
        caller=reader,
        scope_id="scope-a",
        grant_ref="reader",
        authority_incarnation="incarnation",
        historical=True,
    )
    assert result["status"] == "verified"
    assert authority.history_calls[-1][0][0] == "lease-1"


@linux
def test_readback_seals_actual_bytes_intent_and_completion(fixture):
    _, gateway = fixture
    write(gateway)
    result = gateway.readback(
        "lease-1",
        "resource",
        1,
        "token-1",
        "nested/out",
        expected_operation_id="op-1",
        **owner(),
    )
    key = hashlib.sha256(b"op-1").hexdigest()
    records = gateway.root / gateway.MARKER_DIR / "operations"
    intent = json.loads((records / (key + ".intent")).read_text())["body"]
    completed = json.loads((records / (key + ".completed")).read_text())["body"]

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    assert (
        result["sha256"] == hashlib.sha256((gateway.root / "nested/out").read_bytes()).hexdigest()
    )
    assert result["size_bytes"] == result["bytes"] == 3
    assert result["intent_sha256"] == hashlib.sha256(canonical(intent)).hexdigest()
    assert result["completion_sha256"] == hashlib.sha256(canonical(completed)).hexdigest()
    assert result["completion_state"] == "completed"


@linux
@pytest.mark.parametrize(
    "field",
    ["caller", "attempt_id", "runtime_id", "scope_id", "grant_ref", "authority_incarnation"],
)
def test_owner_context_is_mandatory(fixture, field):
    _, gateway = fixture
    with pytest.raises(EffectUnavailable):
        write(gateway, **{field: None})


@linux
def test_scope_and_registry_are_persistently_bound(fixture):
    authority, gateway = fixture
    exposed = gateway.resource_paths
    exposed["resource"] = "elsewhere"
    assert gateway.resource_paths["resource"] == "nested/out"
    for changes in ({"scope_id": "other"}, {"resource_paths": {"resource": "elsewhere"}}):
        config = {"scope_id": "scope-a", "resource_paths": {"resource": "nested/out"}}
        config.update(changes)
        with pytest.raises(ValueError):
            LocalFileEffectGateway(authority, gateway.root, **config)
    with pytest.raises(EffectUnavailable):
        write(gateway, scope_id="other")


@linux
@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/absolute",
        "nested/../out",
        ".acs-effect-markers/config.json",
        "nested/.acs-effect-markers/secret",
        "C:/data",
        "nested\\out",
    ],
)
def test_metadata_and_traversal_are_not_resource_paths(tmp_path, path):
    with pytest.raises(ValueError):
        LocalFileEffectGateway(None, tmp_path / "root", resource_paths={"r": path})
    assert not (tmp_path / "root").exists()


@linux
@pytest.mark.parametrize("part", ["root", "root-parent", "target", "target-parent"])
def test_symlink_components_are_rejected(tmp_path, part):
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "out").write_bytes(b"secret")
    if part == "root":
        root.rename(tmp_path / "moved")
        root.symlink_to(outside, target_is_directory=True)
    elif part == "root-parent":
        link = tmp_path / "parent-link"
        link.symlink_to(tmp_path / "outside", target_is_directory=True)
        root = link / "new-root"
    if part.startswith("root"):
        with pytest.raises(OSError):
            LocalFileEffectGateway(None, root)
        assert sorted(p.name for p in outside.iterdir()) == ["out"]
        return
    with LocalFileEffectGateway(
        AuthorityDouble(), root, scope_id="scope-a", resource_paths={"resource": "nested/out"}
    ) as gateway:
        if part == "target":
            (root / "nested/out").symlink_to(outside / "out")
        else:
            (root / "nested").rename(root / "moved")
            (root / "nested").symlink_to(outside, target_is_directory=True)
        with pytest.raises(EffectUnavailable):
            write(gateway)
        assert (outside / "out").read_bytes() == b"secret"


@linux
def test_parent_replacement_between_opens_cannot_redirect_effect(fixture, tmp_path, monkeypatch):
    _, gateway = fixture
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "out").write_bytes(b"secret")
    original = gateway.root / "nested"
    moved = gateway.root / "moved"
    real_open = os.open

    def replace_after_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if path == "nested" and not moved.exists():
            original.rename(moved)
            original.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", replace_after_open)
    assert write(gateway)["status"] == "verified"
    assert (outside / "out").read_bytes() == b"secret"
    assert (moved / "out").read_bytes() == b"new"


@linux
@pytest.mark.parametrize("mode", ["partial", "digest"])
def test_corrupt_intent_is_rejected(fixture, mode):
    _, gateway = fixture
    write(gateway)
    intent = next((gateway.root / gateway.MARKER_DIR / "operations").glob("*.intent"))
    if mode == "partial":
        intent.write_bytes(b'{"body":')
    else:
        record = json.loads(intent.read_text())
        record["body"]["scope_id"] = "tampered"
        intent.write_text(json.dumps(record))
    with pytest.raises(EffectUnavailable):
        write(gateway)


@linux
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_fsync_failure_is_reported_and_temporary_files_cleaned(fixture, monkeypatch, kind):
    _, gateway = fixture
    before = len(os.listdir("/proc/self/fd"))
    real_sync = os.fsync

    def fail_file(fd):
        mode = os.fstat(fd).st_mode
        if stat.S_ISREG(mode) if kind == "file" else stat.S_ISDIR(mode):
            raise OSError("disk error")
        return real_sync(fd)

    monkeypatch.setattr(os, "fsync", fail_file)
    with pytest.raises(EffectUnavailable, match="disk error"):
        write(gateway)
    assert not list(gateway.root.rglob(".tmp-*"))
    assert len(os.listdir("/proc/self/fd")) == before


@linux
def test_recovery_cannot_cross_workitem(fixture):
    authority, gateway = fixture
    write(gateway)
    authority.generation = 2
    authority.work_item_id = "other-work-item"
    with pytest.raises(EffectUnavailable, match="WorkItem"):
        gateway.resume(
            "lease-2", "resource", 2, "token-2", "nested/out", operation_id="op-1", **owner(2)
        )


@linux
def test_fence_rechecked_immediately_before_target_replace(fixture, monkeypatch):
    authority, gateway = fixture
    real_sync = os.fsync

    def expire_after_staging_target(fd):
        target = os.readlink(f"/proc/self/fd/{fd}")
        result = real_sync(fd)
        if "/nested/.tmp-" in target:
            authority.allowed = False
        return result

    monkeypatch.setattr(os, "fsync", expire_after_staging_target)
    with pytest.raises(FencingRejected):
        write(gateway)
    assert not (gateway.root / "nested/out").exists()


@linux
def test_size_growth_and_nonregular_read_are_bounded(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    target = root / "nested/out"
    with LocalFileEffectGateway(
        AuthorityDouble(),
        root,
        scope_id="scope-a",
        max_bytes=4,
        resource_paths={"resource": "nested/out"},
    ) as gateway:
        with pytest.raises(EffectUnavailable):
            write(gateway, payload=b"12345")
        target.write_bytes(b"old")
        inode = target.stat().st_ino
        real_read = os.read
        requests = []

        def grow(fd, count):
            if os.fstat(fd).st_ino == inode:
                requests.append(count)
                if len(requests) == 1:
                    with target.open("ab") as stream:
                        stream.write(b"growing")
            return real_read(fd, count)

        monkeypatch.setattr(os, "read", grow)
        with pytest.raises(EffectUnavailable):
            write(gateway)
        assert requests and max(requests) <= 5
        target.unlink()
        os.mkfifo(target)
        with pytest.raises(EffectUnavailable):
            write(gateway)


@linux
def test_close_releases_handles(fixture):
    _, gateway = fixture
    before = len(os.listdir("/proc/self/fd"))
    owned = len(gateway._fds)
    gateway.close()
    gateway.close()
    assert len(os.listdir("/proc/self/fd")) == before - owned
    with pytest.raises(EffectUnavailable):
        write(gateway)
