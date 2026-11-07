#!/usr/bin/env python3
"""Verify package payload, manifest coverage, and SHA256SUMS (not ACS implementation)."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest=ROOT/'PACKAGE-MANIFEST.json'
    sums=ROOT/'SHA256SUMS.txt'
    doc=json.loads(manifest.read_text(encoding='utf-8'))
    declared={entry['path'] for entry in doc['files']}
    observed={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()}
    excluded={'PACKAGE-MANIFEST.json','SHA256SUMS.txt'}
    if observed - excluded != declared:
        raise SystemExit(f'Manifest coverage mismatch, missing={sorted(observed - excluded - declared)}, surplus={sorted(declared - (observed - excluded))}')
    for entry in doc['files']:
        path=ROOT/entry['path']
        if len(path.read_bytes())!=entry['bytes'] or digest(path)!=entry['sha256']:
            raise SystemExit('File mismatch: '+entry['path'])
    listed={}
    for line in sums.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        h,p=line.split('  ',1)
        if p in listed:raise SystemExit('Duplicate hash entry: '+p)
        listed[p]=h
    if set(listed) != declared|{'PACKAGE-MANIFEST.json'}:
        raise SystemExit('SHA256SUMS coverage mismatch')
    for p,h in listed.items():
        if digest(ROOT/p)!=h:raise SystemExit('SHA256SUMS mismatch: '+p)
    print(f'PASS: {len(declared)} payload files + manifest integrity (product behavior not tested)')
if __name__=='__main__':main()
