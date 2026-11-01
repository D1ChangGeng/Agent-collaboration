"""Physical 1302-1 Codex A -> Windows-host WSL OpenCode Native B."""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from runtime_tests import test_communication_remote_native as base
from runtime_tests.test_communication import CATALOG
from runtime_tests.test_communication import comm as comm_fixture

comm=comm_fixture


@pytest.mark.skipif(os.getenv('ACS_REAL_REVERSE_NATIVE_TEST')!='1',reason='physical reverse Native is explicit opt-in')
def test_physical_remote_codex_to_local_wsl_native_receiver(comm,tmp_path,monkeypatch):
    host=os.environ['ACS_REVERSE_SENDER_SSH_HOST']
    remote_root=os.environ['ACS_REVERSE_SENDER_SOURCE']
    remote_python=os.environ['ACS_REVERSE_SENDER_PYTHON']
    binary=os.environ['ACS_REVERSE_SENDER_CODEX']
    ssh=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',host]

    def launch_remote(f,root,provider_key,endpoint_id=None,transport_seed=None,*,prompt=None):
        assert endpoint_id and transport_seed
        endpoint=f.authority.receiver_transport.load_endpoint(endpoint_id)
        port=endpoint['connection']['locator_port']
        probe='import socket,json;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'
        r=subprocess.run([*ssh,'python3 -'],input=probe.encode(),capture_output=True,check=True,timeout=20)
        dbport=int(r.stdout)
        values=conninfo_to_dict(f.dsn)
        assert values['dbname']=='acs_communication_test' and values['host']=='127.0.0.1'
        tunnel=subprocess.Popen(['ssh','-T','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-N',
            '-R',f'127.0.0.1:{dbport}:127.0.0.1:{values["port"]}',
            '-R',f'127.0.0.1:{port}:127.0.0.1:{port}',host],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        time.sleep(1)
        assert tunnel.poll() is None,'Isolated reverse forwards failed before sender start'
        request={'catalog':CATALOG,'context':asdict(f.clients['a'].service.context),
            'endpoint_id':endpoint_id,'transport_seed':transport_seed,'dsn':make_conninfo(f.dsn,port=dbport),
            'credential':f.clients['a'].credential_provider(),'provider_key':provider_key,'binary':binary,
            'prompt':prompt or 'You are ordinary Agent A in ACS project-alpha. Ask collaborator slot-b for the release label '
            'through ACS. Use the normal invoke default, wait for its explicit reply and report the label. '
            'Use ACS tools only; do not inspect or change files.'}
        out=(root/'a.jsonl').open('wb');err=(root/'a.stderr.txt').open('wb')
        process=subprocess.Popen([*ssh,remote_python+' -I '+remote_root+'/runtime_tests/fixtures/physical_sender_actor.py'],
            stdin=subprocess.PIPE,stdout=out,stderr=err)
        process.stdin.write((json.dumps(request)+'\n').encode());process.stdin.flush()
        class OwnedRemoteSender:
            def poll(self):return process.poll()
            def wait(self,timeout=None):
                try:return process.wait(timeout)
                finally:
                    if process.poll() is not None:
                        process.stdin.close();tunnel.terminate();tunnel.wait(timeout=15);tunnel.stderr.close()
            def terminate(self):
                try:process.stdin.close()
                except OSError:pass
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.terminate()
                finally:
                    tunnel.terminate();tunnel.wait(timeout=15);tunnel.stderr.close()
        return OwnedRemoteSender(),(out,err)

    monkeypatch.setattr(base,'launch_codex',launch_remote)
    monkeypatch.setenv('ACS_REAL_REMOTE_MODEL_TEST','1')
    monkeypatch.setenv('ACS_NATIVE_PROVIDER_RESPONSES','1')
    base.test_physical_signed_receiver_and_independent_reply(comm,tmp_path,monkeypatch,'codex')
    events=[json.loads(line) for line in (tmp_path/'a.jsonl').read_text().splitlines() if line.startswith('{')]
    started=[v for v in events if v.get('type')=='acs.remote_sender_started']
    cleanup=[v for v in events if v.get('type')=='acs.remote_sender_cleanup']
    facts=json.loads((tmp_path/'facts.json').read_text())
    assert len(started)==len(cleanup)==1 and started[0]['hostname']!=facts['hostname']
    assert cleanup[0]['process_stop']['verified'] and cleanup[0]['process_stop']['remaining_pids']==[]
    facts['topology']='physical-remote-codex-to-windows-host-wsl-native'
    facts['sender_observation']=started[0]
    facts['sender_owned_process_cleanup']=cleanup[0]['process_stop']
    (tmp_path/'facts.json').write_text(json.dumps(facts,indent=2))
