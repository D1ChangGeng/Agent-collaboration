#!/usr/bin/env python3
"""Read-only ACS Git/worktree inventory. File existence is NOT completion evidence.

Usage: python tools/capture_state.py --acs /path/to/ACS --out /tmp/acs-state.json
Never mutates or executes files in target repository; never probes credentials or production APIs.
"""
import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

SOURCE_HINTS = (
    'AGENTS.md', 'pyproject.toml', 'runtime/communication.py',
    'runtime/communication_dispatch.py', 'runtime/native_delivery.py',
    'runtime/communication_management.py', 'runtime/communication_core_schema.sql',
    'runtime/codex_driver.py', 'runtime_deployment/receiver_codex.py',
    'runtime_deployment/receiver_opencode.py', 'runtime_tests', 'integration_evidence',
)

def git(root: Path, *args):
    try:
        p = subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True,
                           check=False, timeout=15)
        return {'exit_code': p.returncode, 'value': p.stdout.strip() if p.returncode == 0 else None,
                'error': p.stderr.strip()[:500] if p.returncode != 0 else None}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'exit_code': None, 'value': None, 'error': type(exc).__name__}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--acs',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--orca',help='optional read-only Orca checkout snapshot')
    args=ap.parse_args()
    acs=Path(args.acs).expanduser().resolve()
    if not acs.is_dir():raise SystemExit('ACS directory does not exist')
    output=Path(args.out).expanduser().resolve()
    if output.is_relative_to(acs):raise SystemExit('Refuse writing scan report inside target ACS repository')
    def scan(root):
        status=git(root,'status','--porcelain=v1','-uno')
        diff=git(root,'diff','--binary')
        return {
          'path':str(root),
          'head':git(root,'rev-parse','HEAD'),
          'branch':git(root,'branch','--show-current'),
          'status':status,
          'diff_sha256':hashlib.sha256((diff['value'] or '').encode('utf-8')).hexdigest() if diff['exit_code']==0 else None,
          'has_uncommitted_changes': bool(status['value']) if status['exit_code']==0 else None,
          'path_exists_hints': {p:(root/p).exists() for p in SOURCE_HINTS},
          'warning':'Paths/status are discovery hints ONLY. No completion/qualification inference.',
        }
    report={'schema_version':'acs-state-capture/1','observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'acs':scan(acs),'prior_work_stage':'unknown_do_not_assume',
            'implementation_assessment':'not_performed','qualification_assessment':'not_performed'}
    if args.orca:
        orca=Path(args.orca).expanduser().resolve()
        report['orca']=scan(orca) if orca.is_dir() else {'path':str(orca),'error':'directory_missing'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Wrote read-only facts to {output}. NO completion claims.')

if __name__=='__main__':main()
