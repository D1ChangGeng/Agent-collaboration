#!/usr/bin/env python3
"""Prioritize unresolved P0/P1 change items; no progress is guessed or modified."""
import argparse, json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]

def plan(state, changes):
    statuses={x['id']:x for x in state['items']}
    output=[]
    for tier in ['P0_required','P1_required','P2_optional']:
        for item in changes['items']:
            if item['tier']!=tier:continue
            ob=statuses.get(item['id'])
            st=ob['status'] if ob else 'unassessed'
            if st=='retained_verified':
                if not ob.get('evidence_refs'):
                    output.append((tier,item['id'],'NEEDS_EVIDENCE','claimed verified without evidence'))
                continue
            if tier=='P2_optional' and st in ('unassessed','absent','out_of_scope_now'):
                continue
            action='REVIEW_ONLY' if st=='implemented_needs_evidence' else 'ASSESS' if st=='unassessed' else 'DELTA'
            output.append((tier,item['id'],action,item['title']))
    return output

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);a=p.parse_args()
    data=json.loads(Path(a.state).read_text()); changes=json.loads((BASE/'contracts/change-items.json').read_text())
    for tier,cid,action,title in plan(data,changes):print(f'{tier:12} {cid:5} {action:16} {title}')
    print('Observe and verify each applicable item. This is NOT proof anything is absent or complete.')
if __name__=='__main__':main()
