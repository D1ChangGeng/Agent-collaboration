"""Guard tests only: never execute privileged filesystem or AppArmor changes."""

import builtins
import errno
import importlib.util
import io
import json
import socket
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "acs_helper_manage", Path(__file__).with_name("manage.py")
)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def file_info(**changes):
    fields = {"st_mode": stat.S_IFREG | 0o750, "st_uid": 0, "st_gid": 1005, "st_nlink": 1}
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "changes",
    [
        {"st_uid": 1005},
        {"st_mode": stat.S_IFLNK | 0o777},
        {"st_mode": stat.S_IFREG | 0o775},
        {"st_mode": stat.S_IFREG | 0o757},
        {"st_nlink": 2},
        {"st_gid": 0},
    ],
)
def test_untrusted_file_metadata_rejected(changes):
    with pytest.raises(manage.Refused):
        manage.check_info(file_info(**changes), mode=0o750, gid=1005)


def test_exact_trusted_file_metadata_allowed():
    manage.check_info(file_info(), mode=0o750, gid=1005)


def manifest():
    return {
        "package": manage.PACKAGE,
        "helper": str(manage.HELPER),
        "profile": str(manage.PROFILE),
        "helper_sha256": manage.HELPER_SHA,
        "profile_sha256": manage.PROFILE_SHA,
        "runtime_user": "changgeng",
        "runtime_uid": 1005,
        "runtime_group": "changgeng",
        "runtime_gid": 1005,
        "created_directories": [str(p) for p in manage.CREATE_DIRS],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"helper": "/usr/bin/bwrap"},
        {"profile": "/etc/apparmor.d/unprivileged_userns"},
        {"created_directories": ["/etc"]},
        {"created_directories": [["bad"]]},
        {"runtime_uid": 0},
        {"runtime_gid": True},
        {"helper_sha256": "0" * 64},
    ],
)
def test_manifest_cannot_claim_other_resources(changes):
    with pytest.raises(manage.Refused):
        manage.validate_manifest({**manifest(), **changes})


def test_bundled_profile_matches_pinned_hash_and_has_no_local_overrides():
    data = Path(manage.__file__).with_name("acs-bwrap-userns.profile").read_bytes()
    assert manage.sha(data) == manage.PROFILE_SHA
    assert b"profile acs_bwrap /opt/acs/codex-sandbox/bin/bwrap" in data
    assert b"profile acs_unpriv_bwrap" in data
    assert b"include if exists" not in data


def no_mutations(monkeypatch):
    monkeypatch.setattr(manage.sys, "platform", "linux")
    monkeypatch.setattr(manage.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        manage, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *_: None), raising=False
    )

    @contextmanager
    def directory(*args, **kwargs):
        yield 42

    monkeypatch.setattr(manage, "directory", directory)
    monkeypatch.setattr(manage, "preflight", lambda args: {"manifest": None, "loaded": None})
    monkeypatch.setattr(manage, "read_file", lambda *args, **kwargs: b"root-owned package fixture")

    def mutation(*args, **kwargs):
        pytest.fail("default check attempted a root mutation")

    for name in ("install", "verify_installed", "remove_owned"):
        monkeypatch.setattr(manage, name, mutation)


@pytest.mark.parametrize("action", ["check", "install", "verify", "uninstall"])
def test_every_action_is_check_only_without_apply(monkeypatch, action, capsys):
    no_mutations(monkeypatch)
    assert manage.main([action]) == 0
    assert '"mode": "check-only"' in capsys.readouterr().out


def test_apply_requires_administrator(monkeypatch):
    monkeypatch.setattr(manage.sys, "platform", "linux")
    monkeypatch.setattr(manage.os, "geteuid", lambda: 1005, raising=False)
    with pytest.raises(manage.Refused, match="root"):
        manage.main(["install", "--apply"])


def test_uninstall_requires_operator_capacity_stop_confirmation(monkeypatch):
    no_mutations(monkeypatch)
    with pytest.raises(manage.Refused, match="capacity-stopped"):
        manage.main(["uninstall", "--apply"])


def test_check_parser_never_loads_kernel_or_cache(monkeypatch):
    monkeypatch.setattr(manage, "read_file", lambda *args, **kwargs: b"trusted parser fixture")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(manage.subprocess, "run", run)
    manage.parse_profile(b"fixture")
    assert calls[0][0][1:] == ["--skip-kernel-load", "--skip-cache"]
    assert calls[0][1]["input"] == b"fixture"


def test_live_capacity_blocks_uninstall_before_disabling_helper(monkeypatch):
    monkeypatch.setattr(manage, "existing_assets", lambda *args, **kwargs: None)

    def busy():
        raise manage.Refused("package capacity not proven stopped")

    monkeypatch.setattr(manage, "matching_capacity", busy)
    monkeypatch.setattr(
        manage.os,
        "fchmod",
        lambda *_: pytest.fail("helper admission changed before stop check"),
        raising=False,
    )
    with pytest.raises(manage.Refused, match="capacity"):
        manage.remove_owned({"manifest": manifest()}, b"fixture")


def test_foreign_owned_file_is_never_unlinked(monkeypatch):
    monkeypatch.setattr(manage, "read_file", lambda *args, **kwargs: b"foreign resource")
    monkeypatch.setattr(
        manage.os, "unlink", lambda *args, **kwargs: pytest.fail("foreign file unlinked")
    )
    with pytest.raises(manage.Refused, match="not matching"):
        manage.remove_file(manage.PROFILE, b"owned bytes", mode=0o644)


def test_uninstall_preflight_does_not_require_current_source_or_live_user(monkeypatch):
    monkeypatch.setattr(manage.sys, "platform", "linux")
    owned_helper = b"pinned installed helper"
    monkeypatch.setattr(manage, "HELPER_SHA", manage.sha(owned_helper))
    installed = manifest()
    profile = Path(manage.__file__).with_name("acs-bwrap-userns.profile").read_bytes()
    monkeypatch.setattr(manage, "bundled_profile", lambda: profile)
    monkeypatch.setattr(manage, "state", lambda: (installed, manage.canonical(installed)))

    def read(path, **kwargs):
        if path == manage.SOURCE:
            pytest.fail("rollback consulted upgraded distribution source")
        return owned_helper if path == manage.HELPER else profile

    monkeypatch.setattr(manage, "read_file", read)
    monkeypatch.setattr(
        manage, "runtime_identity", lambda *_: pytest.fail("rollback required deleted user lookup")
    )
    monkeypatch.setattr(manage, "parse_profile", lambda *_: None)
    monkeypatch.setattr(manage, "loaded_profiles", lambda: manage.ENFORCING_PROFILES)
    monkeypatch.setattr(
        manage,
        "sysctls",
        lambda **kwargs: (
            {"unchanged": "0"}
            if kwargs["require_expected"] is False
            else pytest.fail("rollback required global sysctl change")
        ),
    )
    result = manage.preflight(SimpleNamespace(action="uninstall", apply=False))
    assert result["uid"] == installed["runtime_uid"]
    assert result["helper"] == owned_helper


def test_failed_recheck_does_not_delete_preexisting_install(monkeypatch):
    @contextmanager
    def directory(*args, **kwargs):
        yield 42

    installed = manifest()
    monkeypatch.setattr(manage, "directory", directory)
    monkeypatch.setattr(manage, "state", lambda: (installed, manage.canonical(installed)))
    monkeypatch.setattr(manage, "read_file", lambda *args, **kwargs: b"existing owned file")
    monkeypatch.setattr(manage, "loaded_profiles", lambda: manage.ENFORCING_PROFILES)
    monkeypatch.setattr(
        manage, "remove_owned", lambda *_: pytest.fail("existing installation was removed")
    )

    def failed(_):
        raise manage.Refused("injected verification failure")

    monkeypatch.setattr(manage, "verify_installed", failed)
    with pytest.raises(manage.Refused, match="injected"):
        manage.install(SimpleNamespace(), {"gid": 1005})


def test_unprivileged_probes_share_explicit_uid_gid_and_empty_groups(monkeypatch):
    calls = []
    monkeypatch.setattr(manage.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    manage.run_unprivileged(["probe"], {"uid": 1005, "gid": 1006})
    assert calls == [(["probe"], {
        "cwd": "/", "env": manage.ENV, "user": 1005, "group": 1006,
        "extra_groups": [], "capture_output": True, "timeout": 15, "check": False,
    })]


def postflight_fixture(monkeypatch, fault=None):
    """Guard simulation with real temporary files; no UID switch or mounts."""
    info = {"manifest": manifest(), "uid": 1005, "gid": 1006, "sysctls": {"unchanged": "1"}}
    monkeypatch.setattr(manage, "existing_assets", lambda *args, **kwargs: None)
    monkeypatch.setattr(manage, "loaded_profiles", lambda: manage.ENFORCING_PROFILES)
    monkeypatch.setattr(manage.os, "readlink", lambda path: "host-net")
    monkeypatch.setattr(manage.os.path, "islink", lambda path: False)
    monkeypatch.setattr(manage, "sysctls", lambda: info["sysctls"])
    modes, calls = [], []
    chmod = Path.chmod

    def track_mode(path, mode, *args, **kwargs):
        modes.append((path.name, mode))
        return chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", track_mode)

    @contextmanager
    def fixture(selected):
        assert selected is info
        with tempfile.TemporaryDirectory(prefix="acs-bwrap-verify-") as temporary:
            root = Path(temporary)
            inp = root / "input"
            inp.mkdir()
            source, outside = inp / "probe.txt", root / "outside-scope.txt"
            source.write_bytes(b"acs-readonly-sentinel\n")
            outside.write_text("synthetic outside scope")
            for path, mode in ((root, 0o711), (inp, 0o711), (source, 0o600), (outside, 0o600)):
                path.chmod(mode)
            # This test isolates postflight orchestration. Native FD identity
            # checks have their own isolated Linux subprocess tests below.
            yield SimpleNamespace(input=inp, outside=outside, read=source.read_bytes)

    monkeypatch.setattr(manage, "verification_fixture", fixture)

    def result(code, proof):
        return SimpleNamespace(returncode=code, stdout=json.dumps(proof).encode(), stderr=b"injected")

    def run(argv, selected):
        assert selected is info
        calls.append(list(argv))
        if argv[0] == "/usr/bin/python3":
            assert argv[1:4] == ["-I", "-c", manage.HOST_WRITE_CODE]
            assert argv[-2:] == [str(info["uid"]), str(info["gid"])]
            source = Path(argv[4])
            assert source.read_text() == "acs-readonly-sentinel\n"
            return result(1 if fault == "host_not_writable" else 0, {
                "host_writable": True,
                "uid": 0 if fault == "wrong_host_uid" else info["uid"], "gid": info["gid"],
            })
        index = argv.index("/input")
        source = Path(argv[index - 1]) / "probe.txt"
        assert argv[-3] == manage.VERIFY_CODE
        assert source.read_text() == "acs-readonly-sentinel\n"
        if argv[index - 2] == "--ro-bind":
            if fault == "readonly_writable":
                source.write_bytes(b"acs-write-control\n")
                return result(42, {"readonly": False, "write_errno": None})
            if fault == "readonly_host_changed":
                source.write_text("changed behind verifier")
            return result(0, {"readonly": True, "write_errno": 30})
        assert argv[index - 2] == "--bind"
        if fault == "writable_still_denied":
            return result(0, {"readonly": True, "write_errno": 13})
        if fault != "writable_no_host_change":
            source.write_bytes(b"acs-write-control\n")
        return result(42, {"readonly": False, "write_errno": None})

    monkeypatch.setattr(manage, "run_unprivileged", run)
    return info, calls, modes


def test_postflight_requires_three_controls_and_changes_only_input_mount(monkeypatch):
    info, calls, modes = postflight_fixture(monkeypatch)
    proof = manage.verify_installed(info)
    assert len(calls) == 3
    assert ("probe.txt", 0o600) in modes and ("input", 0o711) in modes
    readonly, writable = calls[1:]
    differences = [(left, right) for left, right in zip(readonly, writable, strict=True) if left != right]
    assert differences == [("--ro-bind", "--bind")]
    assert proof["readonly"] is True
    assert proof["host_write_control"] == {"host_writable": True, "uid": 1005, "gid": 1006}
    assert proof["readonly_host_sentinel_preserved"] is True
    assert proof["writable_bind_control"]["readonly_verifier_exit"] == 42
    assert proof["writable_bind_control"]["host_write_observed"] is True


@pytest.mark.parametrize("fault,reason,call_count", [
    ("host_not_writable", "host writable control failed", 1),
    ("wrong_host_uid", "host writable control did not restore", 1),
    ("readonly_writable", "strict post-install probe failed", 2),
    ("readonly_host_changed", "readonly sentinel changed", 2),
    ("writable_still_denied", "writable mount did not fail", 3),
    ("writable_no_host_change", "writable mount control did not change", 3),
])
def test_postflight_rejects_missing_or_false_controls(monkeypatch, fault, reason, call_count):
    info, calls, _ = postflight_fixture(monkeypatch, fault)
    with pytest.raises(manage.Refused, match=reason):
        manage.verify_installed(info)
    assert len(calls) == call_count


def test_host_control_code_performs_real_write_and_restores_fixture(tmp_path, monkeypatch, capsys):
    # Filesystem operations are real; UID/GID observations are injected only
    # to exercise this script on a non-root Windows guard-test runner.
    source = tmp_path / "probe.txt"
    source.write_text("acs-readonly-sentinel\n")
    monkeypatch.setattr(manage.sys, "argv", ["control", str(source), "1005", "1006"])
    monkeypatch.setattr(manage.os, "geteuid", lambda: 1005, raising=False)
    monkeypatch.setattr(manage.os, "getegid", lambda: 1006, raising=False)
    monkeypatch.setattr(manage.os, "getgroups", list, raising=False)
    exec(compile(manage.HOST_WRITE_CODE, "<host-control-test>", "exec"), {})  # noqa: S102 -- fixed package probe
    assert source.read_text() == "acs-readonly-sentinel\n"
    assert json.loads(capsys.readouterr().out) == {"host_writable": True, "uid": 1005, "gid": 1006}


@pytest.mark.parametrize("value", [b"not-json", b"[]", b"null"])
def test_probe_result_rejects_malformed_control_proof(value):
    with pytest.raises(manage.Refused, match="proof"):
        manage.probe_json(SimpleNamespace(returncode=0, stdout=value, stderr=b""), 0, "probe failed")


@pytest.mark.parametrize("readonly,capabilities,label", [
    (True, 0, "acs_bwrap//&acs_unpriv_bwrap (enforce)"),
    (False, 0, "acs_bwrap//&acs_unpriv_bwrap (enforce)"),
    (False, 1, "acs_bwrap//&acs_unpriv_bwrap (enforce)"),
    (False, 0, "acs_bwrap//&acs_unpriv_bwrap (complain)"),
    (False, 0, "acs_bwrap//&fake_acs_unpriv_bwrap (enforce)"),
    (False, 0, "acs_bwrap//&acs_unpriv_bwrap//&extra (enforce)"),
    (False, 0, "acs_unpriv_bwrap (enforce)"),
])
def test_same_verifier_checks_security_and_distinguishes_writable_input(
    tmp_path, monkeypatch, capsys, readonly, capabilities, label,
):
    """Real temporary writes; /proc, namespace and EROFS are injected observations."""
    source = tmp_path / "probe.txt"
    source.write_text("acs-readonly-sentinel\n")
    source.chmod(0o600)
    real_open = builtins.open
    proc = {
        "/proc/self/status": f"CapEff:\t{capabilities:x}\nCapPrm:\t{capabilities:x}\n",
        "/proc/self/attr/current": label + "\n",
        "/proc/net/route": "Iface Destination Gateway\n",
    }

    def controlled_open(path, mode="r", *args, **kwargs):
        if path == "/input/probe.txt":
            if readonly and mode == "w":
                raise OSError(errno.EROFS, "injected readonly mount")
            return real_open(source, mode, *args, **kwargs)
        if path in proc:
            return io.StringIO(proc[path])
        return real_open(path, mode, *args, **kwargs)

    exists = manage.os.path.exists
    monkeypatch.setattr(manage.os.path, "exists", lambda path: False if path == "/outside-test" else exists(path))
    monkeypatch.setattr(manage.os, "readlink", lambda path: "sandbox-net")
    monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr(manage.sys, "argv", ["probe", "host-net", "/outside-test"])
    monkeypatch.setattr(builtins, "open", controlled_open)
    if capabilities or label != "acs_bwrap//&acs_unpriv_bwrap (enforce)":
        with pytest.raises(AssertionError):
            exec(compile(manage.VERIFY_CODE, "<mount-control-test>", "exec"), {})  # noqa: S102 -- fixed package probe
        assert source.read_text() == "acs-readonly-sentinel\n"
        assert capsys.readouterr().out == ""
    else:
        with pytest.raises(SystemExit) as outcome:
            exec(compile(manage.VERIFY_CODE, "<mount-control-test>", "exec"), {})  # noqa: S102 -- fixed package probe
        assert outcome.value.code == (0 if readonly else 42)
        proof = json.loads(capsys.readouterr().out)
        assert proof["readonly"] is readonly
        assert proof["cap_eff"] == proof["cap_prm"] == 0
        assert proof["separate_netns"] and proof["outside_source_hidden"]
        assert source.read_text() == ("acs-readonly-sentinel\n" if readonly else "acs-write-control\n")


def test_loaded_profiles_preserves_modes_and_ignores_unrelated_profiles():
    assert manage.parse_loaded_profiles([
        "unrelated (complain)\n", "acs_bwrap (enforce)\n", "acs_unpriv_bwrap (complain)\n",
    ]) == {"acs_bwrap": "enforce", "acs_unpriv_bwrap": "complain"}


@pytest.mark.parametrize("lines", [
    ["acs_bwrap"], ["acs_bwrap (enforce"],
    ["acs_bwrap (enforce)", "acs_bwrap (complain)"],
])
def test_loaded_profiles_rejects_missing_or_ambiguous_modes(lines):
    with pytest.raises(manage.Refused, match="mode"):
        manage.parse_loaded_profiles(lines)


@pytest.mark.parametrize("profiles", [
    {"acs_bwrap": "enforce"},
    {"acs_bwrap": "complain", "acs_unpriv_bwrap": "enforce"},
    {"acs_bwrap": "enforce", "acs_unpriv_bwrap": "complain"},
    {"acs_bwrap": "enforce", "acs_unpriv_bwrap": "unconfined"},
])
def test_postflight_requires_both_enforcing_profiles_before_probes(monkeypatch, profiles):
    info, calls, _ = postflight_fixture(monkeypatch)
    monkeypatch.setattr(manage, "loaded_profiles", lambda: profiles)
    with pytest.raises(manage.Refused, match="enforce mode"):
        manage.verify_installed(info)
    assert calls == []


PINNED_FIXTURE_PROBE = r"""
import importlib.util,json,os,pathlib,sys,tempfile
spec=importlib.util.spec_from_file_location("fixture_probe_manage",sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
fault=sys.argv[2]
# Root ownership admission is covered by guard tests. This subprocess remains
# the ordinary test UID; only actual directory/file FD defenses run natively.
m.check_info=lambda *a,**k:None
with tempfile.TemporaryDirectory(prefix="acs-pinned-guard-") as temporary:
    parent=pathlib.Path(temporary);m.MANIFEST=parent/"manifest.json"
    outside=parent/"outside";outside.mkdir();secret=outside/"probe.txt";secret.write_bytes(b"outside synthetic marker")
    fchown=os.fchown;changed=[]
    def track_chown(fd,uid,gid):
        changed.append(fd);return fchown(fd,uid,gid)
    m.os.fchown=track_chown
    with m.verification_fixture({"uid":os.getuid(),"gid":os.getgid()}) as f:
        assert changed==[f._probe_fd]
        assert os.fstat(f._entries[0][2]).st_uid==os.getuid()
        assert os.fstat(f._entries[1][2]).st_mode & 0o777==0o711
        assert f.read()==b"acs-readonly-sentinel\n"
        source=f.input/"probe.txt";restore=lambda:None;requests=[]
        if fault in ("leaf_symlink","leaf_fifo","leaf_regular"):
            source.unlink()
            if fault=="leaf_symlink":source.symlink_to(secret)
            elif fault=="leaf_fifo":os.mkfifo(source)
            else:source.write_bytes(b"acs-readonly-sentinel\n")
        elif fault in ("input_symlink","root_symlink"):
            target=f.input if fault=="input_symlink" else f.input.parent
            moved=target.with_name(target.name+"-original");target.rename(moved);target.symlink_to(outside,target_is_directory=True)
            def restore():
                target.unlink();moved.rename(target)
        elif fault=="oversize":source.write_bytes(b"x"*1024)
        elif fault=="growth_during_read":
            real_read=os.read
            def growing(fd,count):
                if fd==f._probe_fd:
                    requests.append(count)
                    with source.open("ab") as stream:stream.write(b"x"*1024)
                return real_read(fd,count)
            m.os.read=growing
        try:
            try:f.read()
            except m.Refused:pass
            else:raise AssertionError("substituted or oversized fixture accepted")
        finally:restore()
        assert secret.read_bytes()==b"outside synthetic marker"
        assert not requests or max(requests)<=65
        print(json.dumps({"fault":fault,"refused":True,"outside_unchanged":True,"max_read":max(requests,default=0)}))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="native Linux dir_fd test; no root changes")
@pytest.mark.parametrize("fault", [
    "leaf_symlink", "leaf_fifo", "leaf_regular", "input_symlink", "root_symlink", "oversize", "growth_during_read",
])
def test_pinned_fixture_substitution_and_growth_fail_without_blocking(fault):
    completed = subprocess.run(
        [sys.executable, "-I", "-c", PINNED_FIXTURE_PROBE, manage.__file__, fault],
        capture_output=True, text=True, timeout=5, check=True,
    )
    result = json.loads(completed.stdout)
    assert result["fault"] == fault and result["refused"] and result["outside_unchanged"]
    assert result["max_read"] <= 65
