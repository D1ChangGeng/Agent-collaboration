#!/usr/bin/env python3
"""Check the package checksum list without modifying the package."""
from __future__ import annotations
import hashlib
from pathlib import Path

def main() -> int:
    root=Path(__file__).resolve().parents[1]
    failures=[]
    count=0
    try:
        lines=(root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
        for line in lines:
            if not line.strip():continue
            expected,name=line.split('  ',1)
            path=(root/name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                failures.append(name+': missing or unsafe path');continue
            actual=hashlib.sha256(path.read_bytes()).hexdigest();count+=1
            if actual!=expected:failures.append(name+': digest mismatch')
    except (OSError,ValueError) as exc:
        print(f'Cannot verify checksums: {exc}');return 1
    if failures:
        print('\n'.join(failures));return 1
    print(f'PASS: {count} file checksums matched. This is package integrity only.')
    return 0
if __name__=='__main__':raise SystemExit(main())
