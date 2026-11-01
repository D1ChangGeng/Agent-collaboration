"""Owned remote Codex sender; bootstrap secrets arrive only on stdin."""
from __future__ import annotations

import getpass
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime.posix_process_supervisor import PosixProcessSupervisor


def main():
    request = json.loads(sys.stdin.readline())
    base = Path(tempfile.mkdtemp(prefix='acs-physical-sender-'))
    base.chmod(0o700)
    home, work = base/'codex-home', base/'work'
    home.mkdir(mode=0o700);work.mkdir(mode=0o700)
    catalog = base/'catalog.json'
    catalog.write_text(json.dumps(request['catalog']));catalog.chmod(0o600)
    surface = base/'surface.json'
    surface.write_text(json.dumps({'context':request['context'],'access_mode':'owner',
        'remote_endpoints':[{'endpoint_id':request['endpoint_id'],
            'authority_signing_key_ref':{'kind':'environment','name':'ACS_A_TRANSPORT_SEED'}}],
        'dsn_ref':{'kind':'environment','name':'ACS_A_DSN'},
        'credential_ref':{'kind':'environment','name':'ACS_A_CREDENTIAL'}}));surface.chmod(0o600)
    wrapper=base/'mcp.py'
    wrapper.write_text('import sys\nsys.dont_write_bytecode=True\nsys.path.insert(0,'+repr(str(ROOT))+')\n'
        'from runtime.project_entry import main\nraise SystemExit(main('+repr(['--config',str(surface),
        '--catalog',str(catalog),'--profile','engineer'])+'))\n');wrapper.chmod(0o600)
    config=['model="gpt-6.1-sol"','model_provider="acs_test"','approval_policy="never"',
        'sandbox_mode="read-only"','project_doc_max_bytes=0','[features]','apps=false','plugins=false',
        '[model_providers.acs_test]','name="Isolated approved Provider"',
        'base_url="https://api.payapionline.top/v1"','wire_api="responses"',
        'env_key="ACS_A_PROVIDER_KEY"','requires_openai_auth=false','supports_websockets=false',
        '[mcp_servers.acs]','command='+json.dumps(sys.executable),
        'args='+json.dumps(['-I',str(wrapper)]),'required=true','startup_timeout_sec=60','tool_timeout_sec=360',
        'env_vars=["ACS_A_DSN","ACS_A_CREDENTIAL","ACS_A_TRANSPORT_SEED"]',
        'tools={send_message={approval_mode="approve"}}']
    (home/'config.toml').write_text('\n'.join(config)+'\n');(home/'config.toml').chmod(0o600)
    env={k:v for k,v in os.environ.items() if not k.startswith(('CODEX_','OPENCODE_','ACS_'))}
    env.update(CODEX_HOME=str(home),ACS_A_PROVIDER_KEY=request['provider_key'],ACS_A_DSN=request['dsn'],
        ACS_A_CREDENTIAL=request['credential'],ACS_A_TRANSPORT_SEED=request['transport_seed'])
    supervisor=PosixProcessSupervisor(termination_timeout=10)
    version=subprocess.run([request['binary'],'--version'],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    print(json.dumps({'type':'acs.remote_sender_started','hostname':socket.gethostname(),
        'account':getpass.getuser(),'version':version}),flush=True)
    owned=supervisor.launch([request['binary'],'exec','--ephemeral','--json','--skip-git-repo-check',
        '--sandbox','read-only','-C',str(work),request['prompt']],cwd=str(work),env=env,label=base.name)
    owned.process.stdin.close()
    def drain(stream,target):
        while chunk:=stream.read1(65536):
            target.write(chunk);target.flush()
    threads=[threading.Thread(target=drain,args=(owned.process.stdout,sys.stdout.buffer)),
        threading.Thread(target=drain,args=(owned.process.stderr,sys.stderr.buffer))]
    for thread in threads:thread.start()
    reason='completed'
    try:
        end=time.monotonic()+480
        while owned.process.poll() is None:
            ready,_,_=select.select([sys.stdin],[],[],0.25)
            if ready and sys.stdin.readline() in ('','stop\n'):
                reason='controller_closed';break
            if time.monotonic()>end:reason='bounded_timeout';break
    finally:
        proof=supervisor.terminate_tree(owned)
        for thread in threads:thread.join(12)
        supervisor.close()
    print(json.dumps({'type':'acs.remote_sender_cleanup','reason':reason,'process_stop':proof}),flush=True)
    return 0 if reason=='completed' and owned.process.returncode==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
