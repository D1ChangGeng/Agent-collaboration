#!/usr/bin/env python3
"""Read-only Git baseline capture. Does not fetch, checkout, reset or edit a repository."""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path

def git(repo: Path, *args: str) -> bytes:
    result=subprocess.run(['git','-C',str(repo),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    return result.stdout

def capture(repo: Path) -> dict:
    status=git(repo,'status','--porcelain=v1')
    # Hash only; do not export credential-bearing remote URLs or dirty source text.
    dirty_diff=git(repo,'diff','HEAD','--binary')
    return {'commit':git(repo,'rev-parse','HEAD').decode().strip(),'tree':git(repo,'rev-parse','HEAD^{tree}').decode().strip(),'dirty':bool(status),'status_sha256':hashlib.sha256(status).hexdigest(),'tracked_diff_sha256':hashlib.sha256(dirty_diff).hexdigest(),'untracked_present':any(line.startswith(b'?? ') for line in status.splitlines()),'note':'Untracked bytes are not captured. Preserve them; baseline is not a source archive.'}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--acs',required=True,type=Path);p.add_argument('--orca',type=Path);p.add_argument('--out',required=True,type=Path)
    args=p.parse_args()
    try:
        value={'observed_at':datetime.now(timezone.utc).isoformat(),'acs':capture(args.acs),'orca':capture(args.orca) if args.orca else None}
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (OSError,subprocess.SubprocessError) as exc:
        print(f'Baseline capture failed: {exc}');return 1
    print(args.out);return 0
if __name__=='__main__':raise SystemExit(main())
