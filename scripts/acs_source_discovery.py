"""Observe one explicitly scoped Source checkout on its actual machine.

The result is a discovery candidate. Project adoption, SourceBinding, Grants,
source synchronization and Runtime installation have separate write boundaries.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from textwrap import indent
from urllib.parse import urlsplit

from acs_bootstrap import HOST_PROBE, machine_binding, observe_machine, transport_command

SCHEMA = "acs-source-discovery/1"

# The same bounded observation runs locally or on the selected SSH/WSL host.
# All target paths are stdin data, never interpolated into a shell command.
SOURCE_PROBE = (
    "import contextlib, io, json\n"
    "source_machine_output = io.StringIO()\n"
    "with contextlib.redirect_stdout(source_machine_output):\n"
    + indent(HOST_PROBE.strip(), "    ")
    + "\nsource_machine_observation = json.loads(source_machine_output.getvalue())\n"
    + r'''
import json, os, stat, subprocess, sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

def safe_path(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_source_path')
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('source_path_contains_traversal')
    if not path.is_absolute():
        if request['remote']:
            raise ValueError('remote_source_path_requires_absolute_path')
        path = Path.cwd() / path
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('source_path_contains_link_or_reparse_alias')
    return path

def locator(value):
    # URL userinfo, query and fragment may contain credentials. SCP syntax keeps
    # only host and repository path; it does not expose its configured username.
    if '://' in value:
        parsed = urlsplit(value)
        if not parsed.hostname:
            raise ValueError('invalid_repository_locator')
        host = '[' + parsed.hostname + ']' if ':' in parsed.hostname else parsed.hostname
        port = ':' + str(parsed.port) if parsed.port else ''
        return urlunsplit((parsed.scheme, host + port, parsed.path, '', ''))
    if '@' in value and ':' in value.split('@', 1)[1]:
        return value.rsplit('@', 1)[1].split('?', 1)[0].split('#', 1)[0]
    if '?' in value or '#' in value:
        return value.split('?', 1)[0].split('#', 1)[0]
    return value

def git(path, *arguments, allow_failure=False):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
        '-c', 'core.untrackedCache=false', '-C', str(path), *arguments],
        capture_output=True, text=True, env=env, timeout=20)
    if result.returncode:
        if allow_failure:
            return None
        raise ValueError('git_source_observation_failed')
    return result.stdout.rstrip('\r\n')

def probe():
    path = safe_path(request['path'])
    result = {'requested_path': request['path'], 'observed_path': str(path)}
    if not path.is_dir():
        return {**result, 'state': 'need_location', 'reason': 'source_directory_missing'}
    # Refuse an aliased repository control directory before asking Git to read it.
    for ancestor in [path, *path.parents]:
        metadata = ancestor / '.git'
        safe_path(str(metadata))
        if metadata.exists():
            break
    root = git(path, 'rev-parse', '--show-toplevel', allow_failure=True)
    if root is None:
        return {**result, 'state': 'need_location', 'reason': 'path_is_not_a_git_checkout'}
    root = safe_path(root)
    safe_path(git(root, 'rev-parse', '--absolute-git-dir'))
    common = git(root, 'rev-parse', '--git-common-dir')
    safe_path(common if Path(common).is_absolute() else str(root / common))
    commit = git(root, 'rev-parse', '--verify', 'HEAD', allow_failure=True)
    if commit is None:
        return {**result, 'state': 'need_location', 'reason': 'checkout_has_no_commit',
                'repository_root': str(root)}
    tree = git(root, 'rev-parse', commit + '^{tree}')
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD', allow_failure=True)
    status = git(root, 'status', '--porcelain=v1',
                 '--untracked-files=all' if request['include_untracked'] else '--untracked-files=no')
    remotes = []
    for name in git(root, 'remote').splitlines():
        urls = git(root, 'remote', 'get-url', '--all', name)
        remotes.extend({'name': name, 'locator': locator(url)} for url in urls.splitlines())
    management = []
    if request.get('management_path'):
        management.append(safe_path(request['management_path']))
    else:
        for parent in [path, *path.parents]:
            management.append(parent)
            if parent == root:
                break
    manifests = []
    for candidate in management:
        if candidate != root and root not in candidate.parents:
            raise ValueError('management_path_outside_source_checkout')
        manifest_path = safe_path(str(candidate / '.agents' / 'manifest.json'))
        if manifest_path.is_file():
            if manifest_path.stat().st_size > 1024 * 1024:
                raise ValueError('management_manifest_too_large')
            value = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('management_manifest_invalid')
            if value.get('kind') == 'project-collaboration-root':
                manifests.append({'management_root': str(candidate),
                    'root_id': value.get('root_id'), 'project_id': value.get('project_id')})
    if request.get('management_path') and not manifests:
        raise ValueError('selected_management_root_has_no_manifest')
    if git(root, 'rev-parse', '--verify', 'HEAD') != commit:
        raise ValueError('source_head_changed_during_probe')
    if git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD', allow_failure=True) != branch:
        raise ValueError('source_branch_changed_during_probe')
    final_status = git(root, 'status', '--porcelain=v1',
                 '--untracked-files=all' if request['include_untracked'] else '--untracked-files=no')
    if final_status != status:
        raise ValueError('source_working_tree_changed_during_probe')
    return {**result, 'state': 'observed_candidate', 'repository_root': str(root),
        'commit': commit, 'tree': tree, 'branch': branch, 'detached_head': branch is None,
        'working_tree': 'dirty' if status else 'clean' if request['include_untracked']
            else 'tracked_clean_untracked_unobserved', 'status': status.splitlines(),
        'working_tree_scope': 'tracked_and_untracked' if request['include_untracked'] else 'tracked_only',
        'untracked_observed': request['include_untracked'], 'remotes': remotes,
        'management_roots': manifests, 'management_root': manifests[0]['management_root']
            if len(manifests) == 1 else None,
        'project_id': manifests[0]['project_id'] if len(manifests) == 1 else None,
        'root_id': manifests[0]['root_id'] if len(manifests) == 1 else None}

request = json.load(sys.stdin)
try:
    result = probe()
except (ValueError, OSError, subprocess.SubprocessError) as error:
    # Raw OS/Git exceptions can embed source paths or repository credentials.
    reason = str(error) if isinstance(error, ValueError) else type(error).__name__
    result = {'state': 'unavailable', 'reason': reason, 'requested_path': request['path']}
print(json.dumps({**result, 'source_machine_observation': source_machine_observation}))
''')


def repository_identity(locator: str) -> str:
    """Compare credential-free HTTPS/SSH locators for the same Git repository."""
    if "://" in locator:
        value = urlsplit(locator)
        host = value.hostname or ""
        port = ":" + str(value.port) if value.port else ""
        return (host.lower() + port + "/" + value.path.lstrip("/")).removesuffix(".git")
    if ":" in locator and not Path(locator).is_absolute():
        host, path = locator.rsplit("@", 1)[-1].split(":", 1)
        return (host.lower() + "/" + path).removesuffix(".git")
    return locator.removesuffix(".git")


def discover_source(path: str, *, ssh_target: str | None = None,
                    wsl_distribution: str | None = None, management_path: str | None = None,
                    include_untracked: bool = False, expected_commit: str | None = None,
                    expected_project_id: str | None = None, expected_root_id: str | None = None,
                    expected_repository: str | None = None,
                    expected_machine_id: str | None = None, expected_account: str | None = None,
                    expected_user_home: str | None = None) -> dict:
    if ssh_target and wsl_distribution:
        raise ValueError("select one Source observation transport")
    kind = "ssh" if ssh_target else "wsl" if wsl_distribution else "local"
    target = ssh_target or wsl_distribution
    result = {"schema_version": SCHEMA, "requested_path": path,
              "source_transport": kind, "source_target": target,
              "authorization": "read_only_discovery", "binding_created": False}
    try:
        machine = observe_machine(kind, target)
        expected = {"machine_id": expected_machine_id, "account": expected_account,
                    "user_home": expected_user_home}
        conflicts = [key for key, value in expected.items() if value and machine[key] != value]
        result["source_machine"] = machine
        result["source_machine_binding"] = machine_binding(machine)
        if conflicts:
            return {**result, "state": "conflict", "conflicts": conflicts}
        request = {"path": path, "management_path": management_path,
                   "include_untracked": include_untracked, "remote": kind != "local"}
        command = ([sys.executable, "-c", SOURCE_PROBE] if kind == "local" else
                   transport_command(kind, target, SOURCE_PROBE))
        completed = subprocess.run(command, input=json.dumps(request), capture_output=True,
                                   text=True, check=True, timeout=120)
        observed = json.loads(completed.stdout)
        if not isinstance(observed, dict) or observed.get("state") not in {
                "observed_candidate", "need_location", "unavailable"}:
            raise ValueError("invalid Source observation result")
        actual = observed.pop("source_machine_observation", None)
        if (not isinstance(actual, dict) or actual.get("schema_version") != "acs-install-machine/1"
                or not isinstance(actual.get("machine_id"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", actual.get("machine_id", ""))
                or not all(isinstance(actual.get(key), str) and actual[key]
                           for key in ("account", "hostname", "user_home", "platform", "python"))):
            raise ValueError("Source process machine observation is invalid")
        result.update(observed)
        result["source_machine"] = {**actual, "transport": kind, "locator": target}
        result["source_machine_binding"] = machine_binding(actual)
        if machine_binding(actual) != machine_binding(machine):
            return {**result, "state": "conflict", "conflicts": ["source_machine_binding"],
                    "reason": "source_host_or_account_changed_during_probe",
                    "source_machine_binding_before_probe": machine_binding(machine)}
        if result["state"] == "observed_candidate":
            for key, wanted in {"commit": expected_commit, "project_id": expected_project_id,
                                "root_id": expected_root_id}.items():
                if wanted and result.get(key) != wanted:
                    conflicts.append(key)
            if expected_repository and repository_identity(expected_repository) not in {
                    repository_identity(remote["locator"]) for remote in result["remotes"]}:
                conflicts.append("repository_identity")
            if conflicts:
                result.update(state="conflict", conflicts=conflicts)
        return result
    except (ValueError, OSError, subprocess.SubprocessError):
        return {**result, "state": "unavailable", "reason": "source_host_or_probe_unavailable"}


def analyze_candidates(candidates: list[dict], *, session_source: dict | None = None) -> dict:
    """Select only a unique observed candidate or an exact current-session match.

    Callers pass only paths and machines already authorized for source inspection.
    Session evidence contains repository_root and source_machine_binding.
    """
    usable = [item for item in candidates if item.get("state") == "observed_candidate"]
    matched = [item for item in usable if session_source and all(
        item.get(key) == session_source.get(key)
        for key in ("repository_root", "source_machine_binding"))]
    choices = matched or usable
    if len(choices) == 1 and not any(item.get("state") == "conflict" for item in candidates):
        return {"state": "candidate_identified", "candidate": choices[0],
                "selection_basis": "current_session" if matched else "unique_observed_candidate"}
    return {"state": "needs_selection" if usable else "need_location",
            "required_input": "Source checkout host and exact path",
            "candidates": candidates}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="Source or Management path on its actual host")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--ssh-target", help="explicitly authorized SSH alias or user@host")
    transport.add_argument("--wsl-distribution", help="explicitly selected WSL distribution")
    parser.add_argument("--management-path", help="known nested Management Root on that same host")
    parser.add_argument("--include-untracked", action="store_true")
    for name in ("commit", "project-id", "root-id", "repository", "machine-id", "account", "user-home"):
        parser.add_argument("--expected-" + name)
    arguments = vars(parser.parse_args())
    result = discover_source(**arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "observed_candidate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
