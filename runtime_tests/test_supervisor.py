from __future__ import annotations

import ctypes
import dataclasses
import hashlib
import json
import os
import queue
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runtime import supervisor as supervisor_module
from runtime.supervisor import (
    ContainmentUnavailable,
    DockerBind,
    DockerPolicy,
    DockerSupervisor,
    OwnedProcess,
    OwnershipMismatch,
    Supervisor,
    WindowsJobSupervisor,
    _proc_birth,
)

EVIDENCE = []


def line(process, timeout=5):
    result = queue.Queue()
    def read():
        try:
            result.put(process.stdout.readline().decode("utf-8").strip())
        except (OSError, UnicodeError, ValueError) as error:
            result.put(error)
    threading.Thread(target=read, daemon=True).start()
    value = result.get(timeout=timeout)
    if isinstance(value, BaseException):
        raise value
    if not value:
        raise AssertionError("contained process returned no expected output")
    return value


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("bounded process observation timed out")


def close_streams(handle):
    for stream in (handle.process.stdin, handle.process.stdout, handle.process.stderr):
        if stream is not None:
            stream.close()


@contextmanager
def held_windows_members(supervisor, handle, pids):
    """Pin exact owned process objects so post-kill checks cannot follow PID reuse."""
    api = supervisor.api
    api.dll.OpenProcess.argtypes = [api.w.DWORD, api.w.BOOL, api.w.DWORD]
    api.dll.OpenProcess.restype = api.w.HANDLE
    api.dll.WaitForSingleObject.argtypes = [api.w.HANDLE, api.w.DWORD]
    api.dll.WaitForSingleObject.restype = api.w.DWORD
    held = []
    try:
        for pid in sorted(pids):
            process_handle = api.dll.OpenProcess(0x00100000 | 0x1000, False, pid)
            api.check(process_handle, "OpenProcess(owned test member)")
            process = SimpleNamespace(pid=pid, _handle=process_handle)
            inside = api.w.BOOL()
            api.check(api.dll.IsProcessInJob(process_handle, supervisor._record(handle).backend_ref,
                                            ctypes.byref(inside)), "IsProcessInJob(owned outer Job)")
            held.append((process_handle, {"pid": pid, "birth_ref": api.birth(process),
                                         "image_path": api.image(process), "in_supervisor_job": bool(inside.value)}))
        yield held
    finally:
        for process_handle, _ in held:
            api.dll.CloseHandle(process_handle)


@unittest.skipUnless(os.name == "nt", "Windows JobObject integration requires Windows")
class WindowsContainmentTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = WindowsJobSupervisor()
        self.handles = []
        self.cwd = str(Path(__file__).resolve().parent)
        self.env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
                    "PATH": str(Path(sys.executable).parent)}

    def spawn(self, program, label):
        handle = self.supervisor.launch([sys.executable, "-I", "-S", "-c", program],
                                       cwd=self.cwd, env=self.env, label=label)
        self.handles.append(handle)
        return handle

    def tearDown(self):
        for handle in self.handles:
            proof = self.supervisor.terminate_tree(handle)
            self.assertTrue(proof["verified"])
            self.assertTrue(proof["root_exited"])
            self.assertEqual(proof["remaining_pids"], [])
            close_streams(handle)

    def test_child_grandchild_and_explicit_breakaway_are_contained(self):
        grandchild = "import os,time,json; print(json.dumps({'role':'leaf','pid':os.getpid(),'ppid':os.getppid()}),flush=True); time.sleep(5)"
        child = ("import subprocess,sys,os,time,json; "
                 f"p=subprocess.Popen([sys.executable,'-I','-S','-c',{grandchild!r}]); "
                 "print(json.dumps({'role':'child','pid':os.getpid(),'ppid':os.getppid(),'grandchild':p.pid}),flush=True); time.sleep(5)")
        breakaway_program = "import os,time,json; print(json.dumps({'role':'breakaway','pid':os.getpid(),'ppid':os.getppid()}),flush=True); time.sleep(5)"
        program = (
            "import subprocess,sys,os,time,json\n"
            f"child=subprocess.Popen([sys.executable,'-I','-S','-c',{child!r}])\n"
            "escaped=None\n"
            "try:\n"
            f" escaped=subprocess.Popen([sys.executable,'-I','-S','-c',{breakaway_program!r}],creationflags=0x01000000)\n"
            " result='spawned'\n"
            "except OSError as error:\n"
            " result='denied:'+str(error.winerror)\n"
            "print(json.dumps({'role':'root','pid':os.getpid(),'ppid':os.getppid(),'child':child.pid,"
            "'breakaway':result,'breakaway_launcher_pid':escaped.pid if escaped else None}),flush=True)\n"
            "time.sleep(5)\n")
        handle = self.spawn(program, "windows-descendant-probe")
        messages = []
        while True:
            messages.append(json.loads(line(handle.process)))
            roots = [value for value in messages if value["role"] == "root"]
            required = {"root", "child", "leaf"}
            if roots and roots[0]["breakaway"] == "spawned":
                required.add("breakaway")
            if roots and required.issubset({value["role"] for value in messages}):
                break
        root = next(value for value in messages if value["role"] == "root")
        child = next(value for value in messages if value["role"] == "child")
        self.assertIn(root["breakaway"], ("denied:5", "spawned"))
        expected = {handle.process.pid, root["pid"], root["child"], child["grandchild"]}
        expected.update(value["pid"] for value in messages)
        if root["breakaway"] == "spawned":
            expected.add(root["breakaway_launcher_pid"])
        active = wait_until(lambda: (proof if expected.issubset(set(proof["remaining_pids"])) else None)
                            if (proof := self.supervisor.inspect(handle)) else None)
        self.assertTrue(active["verified"])
        self.assertFalse(active["breakaway_allowed"])
        self.assertTrue(active["kill_on_close"])
        with held_windows_members(self.supervisor, handle, expected) as held:
            self.assertTrue(all(identity["in_supervisor_job"] for _, identity in held))
            identities = [identity for _, identity in held]
            ended = self.supervisor.terminate_tree(handle)
            self.assertEqual(ended["birth_ref"], handle.birth_ref)
            self.assertEqual(ended["remaining_pids"], [])
            for process_handle, identity in held:
                self.assertEqual(self.supervisor.api.dll.WaitForSingleObject(process_handle, 0), 0, identity)
        EVIDENCE.append({"scenario": self.id(), "observed": messages, "member_identities": identities,
                         "active": active, "terminated": ended, "all_pinned_process_handles_exited": True})

    def test_root_exit_does_not_hide_live_descendant(self):
        program = ("import subprocess,sys,json; "
                   "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(30)']); "
                   "print(json.dumps({'child':p.pid}),flush=True)")
        handle = self.spawn(program, "windows-orphan-probe")
        child = json.loads(line(handle.process))["child"]
        handle.process.wait(timeout=5)
        active = self.supervisor.inspect(handle)
        self.assertTrue(active["root_exited"])
        self.assertIn(child, active["remaining_pids"])
        ended = self.supervisor.terminate_tree(handle)
        EVIDENCE.append({"scenario": self.id(), "active": active, "terminated": ended})

    def test_empty_job_enumeration_does_not_hide_unsignaled_member(self):
        program = ("import subprocess,sys,json; "
                   "p=subprocess.Popen([sys.executable,'-I','-S','-c','import time; time.sleep(5)']); "
                   "print(json.dumps({'child':p.pid}),flush=True)")
        handle = self.spawn(program, "windows-pending-exit-proof")
        child = json.loads(line(handle.process))["child"]
        handle.process.wait(timeout=5)
        observed = self.supervisor.inspect(handle)
        self.assertIn(child, observed["remaining_pids"])
        with mock.patch.object(self.supervisor.api, "pids", return_value=[]):
            pending = self.supervisor.inspect(handle)
            self.assertTrue(pending["root_exited"])
            self.assertIn(child, pending["remaining_pids"])
            self.assertIn(child, pending["pending_process_exits"])
            ended = self.supervisor.terminate_tree(handle)
        self.assertTrue(ended["verified"])
        self.assertEqual(ended["remaining_pids"], [])
        EVIDENCE.append({"scenario": self.id(), "evidence_class": "fault_injected_job_enumeration",
                         "real_pending_member": child, "pending": pending, "terminated": ended})

    def test_other_owned_capacity_survives_and_forged_handle_is_rejected(self):
        program = "import os,time; print(os.getpid(),flush=True); time.sleep(30)"
        first = self.spawn(program, "windows-first-capacity")
        other = self.spawn(program, "windows-unrelated-sentinel")
        line(first.process)
        line(other.process)
        with self.assertRaises(OwnershipMismatch):
            self.supervisor.terminate_tree(dataclasses.replace(first))
        ended = self.supervisor.terminate_tree(first)
        survivor = self.supervisor.inspect(other)
        self.assertFalse(survivor["root_exited"])
        self.assertIn(other.process.pid, survivor["remaining_pids"])
        EVIDENCE.append({"scenario": self.id(), "terminated": ended, "sentinel": survivor})

    def test_environment_is_explicit_and_stdio_is_binary(self):
        os.environ["ACHP_SUPERVISOR_SYNTHETIC_SECRET"] = "test-only-not-a-secret"
        try:
            handle = self.spawn(
                "import os,sys,json; print(json.dumps({'marker':os.getenv('ACHP_SUPERVISOR_SYNTHETIC_SECRET')}),flush=True); "
                "data=sys.stdin.buffer.readline(); sys.stdout.buffer.write(data); sys.stdout.buffer.flush()",
                "windows-env-stdio")
            self.assertIsNone(json.loads(line(handle.process))["marker"])
            handle.process.stdin.write(b"roundtrip-bytes\n")
            handle.process.stdin.flush()
            self.assertEqual(line(handle.process), "roundtrip-bytes")
            handle.process.wait(timeout=5)
        finally:
            os.environ.pop("ACHP_SUPERVISOR_SYNTHETIC_SECRET", None)

    def test_kill_on_close_survives_abrupt_supervisor_process_exit(self):
        module_dir = str(Path(supervisor_module.__file__).resolve().parent)
        program = (
            f"import sys; sys.path.insert(0,{module_dir!r})\n"
            "from supervisor import WindowsJobSupervisor\n"
            "import os,json\n"
            "supervisor=WindowsJobSupervisor()\n"
            f"owned=supervisor.launch([sys.executable,'-I','-S','-c','import time; time.sleep(30)'],cwd={self.cwd!r},"
            f"env={self.env!r},label='windows-kill-on-close-child')\n"
            "print(json.dumps({'child':owned.process.pid}),flush=True)\n"
            "os._exit(0)\n")
        handle = self.spawn(program, "windows-supervisor-crash")
        child = json.loads(line(handle.process))["child"]
        handle.process.wait(timeout=5)
        proof = wait_until(lambda: (value if not value["remaining_pids"] else None)
                           if (value := self.supervisor.inspect(handle)) else None)
        self.assertNotIn(child, proof["remaining_pids"])
        EVIDENCE.append({"scenario": self.id(), "abrupt_exit_child": child, "proof": proof})

    def test_failed_job_assignment_never_runs_payload(self):
        original_popen = subprocess.Popen
        created = []
        def capture(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            created.append(process)
            return process
        with (
            mock.patch.object(subprocess, "Popen", side_effect=capture),
            mock.patch.object(self.supervisor.api.dll, "AssignProcessToJobObject", return_value=0),
            self.assertRaises(ContainmentUnavailable),
        ):
            self.supervisor.launch([sys.executable, "-I", "-S", "-c", "raise SystemExit(73)"],
                                   cwd=self.cwd, env=self.env, label="windows-assignment-fault")
        self.assertEqual(len(created), 1)
        self.assertIsNotNone(created[0].poll())
        self.assertNotEqual(created[0].returncode, 73)
        EVIDENCE.append({"scenario": self.id(), "evidence_class": "fault_injected_admission_failure",
                         "suspended_root_pid": created[0].pid, "exit_code": created[0].returncode,
                         "payload_exit_code_not_observed": 73})

    @unittest.skipUnless(os.environ.get("ACHP_SUPERVISOR_NATIVE_CODEX"), "explicit native Codex executable is required")
    def test_native_codex_executable_launches_in_verified_job(self):
        executable = Path(os.environ["ACHP_SUPERVISOR_NATIVE_CODEX"]).resolve()
        handle = self.supervisor.launch([str(executable), "--version"], cwd=self.cwd, env=self.env,
                                        label="windows-native-codex-version")
        self.handles.append(handle)
        version = line(handle.process)
        self.assertIn("codex", version.lower())
        self.assertEqual(handle.process.wait(timeout=5), 0)
        proof = self.supervisor.terminate_tree(handle)
        self.assertTrue(proof["verified"])
        self.assertEqual(Path(proof["root_image"]).resolve(), executable)
        self.assertEqual(proof["remaining_pids"], [])
        EVIDENCE.append({"scenario": self.id(), "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                         "version": version, "proof": proof})


@unittest.skipUnless(os.name == "posix" and os.environ.get("ACHP_SUPERVISOR_DOCKER_IMAGE"),
                     "explicit pinned Linux Docker test image is required")
class DockerContainmentTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = DockerSupervisor(DockerPolicy(image=os.environ["ACHP_SUPERVISOR_DOCKER_IMAGE"]))
        self.handles = []

    def spawn(self, script, label):
        handle = self.supervisor.launch(["/bin/sh", "-c", script], cwd="/tmp",
                                       env={"PATH": "/usr/bin:/bin"}, label=label)
        self.handles.append(handle)
        return handle

    def tearDown(self):
        for handle in self.handles:
            proof = self.supervisor.terminate_tree(handle)
            self.assertTrue(proof["verified"])
            self.assertTrue(proof["root_exited"])
            self.assertEqual(proof["remaining_pids"], [])
            self.assertTrue(proof["container_removed"])
            close_streams(handle)

    def test_setsid_child_grandchild_remain_in_owned_cgroup(self):
        script = "echo root; /bin/sh -c 'setsid /bin/sh -c \"echo grandchild; sleep 30\" & echo child; wait' & wait"
        handle = self.spawn(script, "linux-setsid-probe")
        messages = [line(handle.process) for _ in range(3)]
        self.assertEqual(set(messages), {"root", "child", "grandchild"})
        active = wait_until(lambda: (value if len(value["remaining_pids"]) >= 3 else None)
                            if (value := self.supervisor.inspect(handle)) else None)
        sessions = {}
        for pid in active["remaining_pids"]:
            raw = Path(f"/proc/{pid}/stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            sessions[pid] = {"ppid": int(fields[1]), "session": int(fields[3])}
        self.assertGreater(len({entry["session"] for entry in sessions.values()}), 1)
        self.assertTrue(active["verified"])
        self.assertTrue(active["cgroup_populated"])
        ended = self.supervisor.terminate_tree(handle)
        self.assertEqual(ended["remaining_pids"], [])
        EVIDENCE.append({"scenario": self.id(), "active": active, "sessions": sessions, "terminated": ended})

    def test_other_owned_container_survives_and_handles_cannot_be_forged(self):
        first = self.spawn("echo first; sleep 30", "linux-first-capacity")
        other = self.spawn("echo sentinel; sleep 30", "linux-unrelated-sentinel")
        line(first.process)
        line(other.process)
        with self.assertRaises(OwnershipMismatch):
            self.supervisor.terminate_tree(OwnedProcess(first.process, first.containment_id, first.birth_ref))
        ended = self.supervisor.terminate_tree(first)
        self.assertIsNotNone(first.process.poll())
        self.assertEqual(first.process.wait(timeout=1), first.process.poll())
        survivor = self.supervisor.inspect(other)
        self.assertFalse(survivor["root_exited"])
        self.assertTrue(survivor["verified"])
        EVIDENCE.append({"scenario": self.id(), "terminated": ended, "sentinel": survivor})

    def test_kernel_identity_privileges_and_control_socket_boundary(self):
        handle = self.spawn("echo ready; sleep 30", "linux-kernel-boundary")
        self.assertEqual(line(handle.process), "ready")
        status = dict(line.split(':', 1) for line in Path(f"/proc/{handle.process.pid}/status").read_text().splitlines() if ':' in line)
        self.assertEqual([int(value) for value in status["Uid"].split()], [65534] * 4)
        self.assertEqual(int(status["CapEff"].strip(), 16), 0)
        self.assertEqual(status["NoNewPrivs"].strip(), "1")
        proof = self.supervisor.inspect(handle)
        self.assertTrue(proof["verified"])
        self.assertTrue(proof["read_only_root"])
        self.assertEqual(proof["network"], "none")
        self.assertEqual(proof["capabilities_dropped"], ["ALL"])
        EVIDENCE.append({"scenario": self.id(), "kernel": {key: status[key].strip() for key in ("Uid", "CapEff", "NoNewPrivs")},
                         "proof": proof})

    def test_unconfigured_linux_backend_is_fail_closed(self):
        with self.assertRaises(ContainmentUnavailable):
            Supervisor()
        with self.assertRaises(ValueError):
            DockerSupervisor(DockerPolicy(image="alpine:latest"))

    def test_policy_readback_failure_prevents_container_start(self):
        original_popen = subprocess.Popen
        starts = []
        def capture(argv, *args, **kwargs):
            if argv[:4] == ["docker", "start", "--attach", "--interactive"]:
                starts.append(argv)
            return original_popen(argv, *args, **kwargs)
        with (
            mock.patch.object(subprocess, "Popen", side_effect=capture),
            mock.patch.object(self.supervisor, "_policy_verified", return_value=False),
            self.assertRaises(ContainmentUnavailable),
        ):
            self.supervisor.launch(["/bin/sh", "-c", "exit 73"], cwd="/tmp", env={},
                                   label="linux-policy-denial")
        self.assertEqual(starts, [])
        EVIDENCE.append({"scenario": self.id(), "evidence_class": "fault_injected_admission_failure",
                         "docker_start_calls": 0})

    def test_same_container_restart_invalidates_old_handle_before_any_mutation(self):
        handle = self.spawn("echo original; sleep 30", "linux-incarnation-restart")
        self.handles.remove(handle)  # This fixture explicitly owns both restart incarnations.
        cid = self.supervisor._record(handle).backend_ref
        line(handle.process)
        original = self.supervisor._container(cid)
        current_identity = (original["State"]["StartedAt"], handle.process.pid, _proc_birth(handle.process.pid))
        restarted = None
        try:
            self.supervisor._require_incarnation(cid, handle.containment_id, *current_identity)
            self.supervisor._run(["kill", "--signal=KILL", cid])
            handle.process._transport.wait(timeout=5)
            self.supervisor._run(["start", cid])
            restarted = wait_until(lambda: (value if value["State"]["Running"] and value["State"]["Pid"] > 0 else None)
                                   if (value := self.supervisor._container(cid)) else None)
            current_identity = (restarted["State"]["StartedAt"], int(restarted["State"]["Pid"]),
                                _proc_birth(int(restarted["State"]["Pid"])))
            self.assertNotEqual(current_identity[0], original["State"]["StartedAt"])
            self.assertNotEqual(current_identity[2], self.supervisor._record(handle).details["root_birth"])
            self.assertFalse(self.supervisor.inspect(handle)["verified"])
            raw_run = self.supervisor._run
            mutations = []
            def capture(arguments, **kwargs):
                if arguments[0] in ("kill", "rm"):
                    mutations.append(arguments)
                return raw_run(arguments, **kwargs)
            with mock.patch.object(self.supervisor, "_run", side_effect=capture):
                with self.assertRaises(OwnershipMismatch):
                    self.supervisor.terminate_tree(handle)
                with self.assertRaises(OwnershipMismatch):
                    handle.process.poll()
            self.assertEqual(mutations, [])
            retained = self.supervisor._require_incarnation(cid, handle.containment_id, *current_identity)
            self.assertTrue(retained["State"]["Running"])
            EVIDENCE.append({"scenario": self.id(), "container_id": cid,
                             "original_started_at": original["State"]["StartedAt"],
                             "replacement_started_at": current_identity[0],
                             "replacement_birth": current_identity[2],
                             "old_handle_mutations": mutations, "replacement_survived": True})
        finally:
            # Fixture cleanup has its own fresh, explicitly observed incarnation,
            # never the rejected public handle.
            value = self.supervisor._require_incarnation(cid, handle.containment_id, *current_identity)
            if value["State"]["Running"]:
                self.supervisor._require_incarnation(cid, handle.containment_id, *current_identity)
                self.supervisor._run(["kill", "--signal=KILL", cid])
            wait_until(lambda: not self.supervisor._container(cid)["State"]["Running"])
            self.supervisor._require_incarnation(cid, handle.containment_id, *current_identity)
            self.supervisor._run(["rm", cid])
            close_streams(handle)

    def test_socket_and_fifo_bind_sources_are_rejected_without_daemon_calls(self):
        with tempfile.TemporaryDirectory(prefix="achp-supervisor-bind-kind-") as directory:
            socket_path = str(Path(directory) / "control")
            fifo_path = str(Path(directory) / "stream")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owned_socket:
                owned_socket.bind(socket_path)
                os.mkfifo(fifo_path, 0o600)
                for source in (socket_path, fifo_path):
                    with (
                        self.subTest(source=Path(source).name),
                        mock.patch.object(DockerSupervisor, "_run", side_effect=AssertionError("invalid bind reached Docker")),
                        self.assertRaises(ValueError),
                    ):
                        DockerSupervisor(DockerPolicy(image=self.supervisor.policy.image,
                                                      binds=(DockerBind(source, "/workspace"),)))
            EVIDENCE.append({"scenario": self.id(), "actual_source_types": ["unix_socket", "fifo"],
                             "suffixes": ["", ""], "docker_calls": 0})

    def test_device_stat_mode_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="achp-supervisor-device-mode-") as directory:
            source = Path(directory) / "ordinary"
            source.write_text("owned fixture")
            fake_stat = os.stat_result((stat.S_IFCHR | 0o600, 1, 1, 1, os.getuid(), os.getgid(), 0, 0, 0, 0))
            with (
                mock.patch.object(Path, "lstat", return_value=fake_stat),
                mock.patch.object(DockerSupervisor, "_run", side_effect=AssertionError("device reached Docker")),
                self.assertRaises(ValueError),
            ):
                DockerSupervisor(DockerPolicy(image=self.supervisor.policy.image,
                                              binds=(DockerBind(str(source), "/workspace"),)))
            EVIDENCE.append({"scenario": self.id(), "evidence_class": "fault_injected_stat_device_mode",
                             "real_device_created": False, "docker_calls": 0})

    def test_bind_replaced_with_fifo_after_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="achp-supervisor-bind-swap-") as directory:
            source = Path(directory) / "input"
            source.write_text("owned regular file")
            supervisor = DockerSupervisor(DockerPolicy(image=self.supervisor.policy.image,
                                                       binds=(DockerBind(str(source), "/workspace"),)))
            source.unlink()
            os.mkfifo(source, 0o600)
            with (
                mock.patch.object(supervisor, "_run", side_effect=AssertionError("changed bind reached Docker")),
                self.assertRaises(ContainmentUnavailable),
            ):
                supervisor.launch(["/bin/sh", "-c", "exit 73"], cwd="/tmp", env={}, label="linux-bind-swap")

    def test_each_actual_tmpfs_policy_mutation_is_rejected_before_start(self):
        expected = "rw,nosuid,nodev,noexec,size=16777216"
        variants = {
            "missing_tmp": None,
            "missing_rw": expected.replace("rw,", ""),
            "missing_nosuid": expected.replace("nosuid,", ""),
            "missing_nodev": expected.replace("nodev,", ""),
            "missing_noexec": expected.replace("noexec,", ""),
            "wrong_size": expected.replace("16777216", "33554432"),
            "extra_mount": expected,
            "added_exec": expected + ",exec",
            "duplicate_option": expected + ",nosuid",
        }
        for name, options in variants.items():
            with self.subTest(variant=name):
                raw_run = self.supervisor._run
                original_popen = subprocess.Popen
                starts = []
                readbacks = []
                def altered_run(arguments, *, _options=options, _name=name, _raw_run=raw_run,
                                _readbacks=readbacks, **kwargs):
                    arguments = list(arguments)
                    if arguments[0] == "create":
                        index = arguments.index("--tmpfs")
                        if _options is None:
                            del arguments[index:index + 2]
                        elif _name == "extra_mount":
                            arguments[index:index] = ["--tmpfs", "/extra:" + expected]
                        else:
                            arguments[index + 1] = "/tmp:" + _options
                    value = _raw_run(arguments, **kwargs)
                    if arguments[0] == "inspect" and value.returncode == 0:
                        _readbacks.append(json.loads(value.stdout)[0]["HostConfig"].get("Tmpfs"))
                    return value
                def capture(argv, *args, _starts=starts, _original_popen=original_popen, **kwargs):
                    if argv[:4] == ["docker", "start", "--attach", "--interactive"]:
                        _starts.append(argv)
                    return _original_popen(argv, *args, **kwargs)
                with (
                    mock.patch.object(self.supervisor, "_run", side_effect=altered_run),
                    mock.patch.object(subprocess, "Popen", side_effect=capture),
                    self.assertRaises(ContainmentUnavailable),
                ):
                    self.supervisor.launch(["/bin/sh", "-c", "exit 73"], cwd="/tmp", env={},
                                           label="linux-tmpfs-" + name.replace("_", "-"))
                self.assertEqual(starts, [])
                self.assertTrue(readbacks)
                EVIDENCE.append({"scenario": self.id(), "variant": name,
                                 "actual_docker_tmpfs_readback": readbacks[0], "docker_start_calls": 0})


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    target = os.environ.get("ACHP_SUPERVISOR_EVIDENCE")
    if target:
        Path(target).write_text(json.dumps({"successful": result.wasSuccessful(), "tests_run": result.testsRun,
                                          "skipped": len(result.skipped), "evidence": EVIDENCE,
                                          "supervisor_sha256": hashlib.sha256(Path(supervisor_module.__file__).read_bytes()).hexdigest(),
                                          "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
