import sys
import unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'tools'))
import validate_pack
import plan_gaps
import json

class RevisionTests(unittest.TestCase):
    def test_static_contract(self):validate_pack.validate()
    def test_no_progress_presumption(self):
        state=json.loads((HERE/'handoff/ADOPTION_STATE_TEMPLATE.json').read_text())
        plan=plan_gaps.plan(state,json.loads((HERE/'contracts/change-items.json').read_text()))
        self.assertTrue(plan)
        self.assertTrue(all(a[2]=='ASSESS' for a in plan))
        self.assertFalse(any(a[0]=='P2_optional' for a in plan))
    def test_retained_item_not_rescheduled(self):
        state=json.loads((HERE/'handoff/ADOPTION_STATE_TEMPLATE.json').read_text())
        state['items'][0]['status']='retained_verified'
        state['items'][0]['evidence_refs']=['evidence:verified-test-id']
        plan=plan_gaps.plan(state,json.loads((HERE/'contracts/change-items.json').read_text()))
        self.assertFalse(any(a[1]==state['items'][0]['id'] for a in plan))
    def test_claimed_pass_without_evidence_is_not_accepted(self):
        state=json.loads((HERE/'handoff/ADOPTION_STATE_TEMPLATE.json').read_text())
        state['items'][0]['status']='retained_verified'
        plan=plan_gaps.plan(state,json.loads((HERE/'contracts/change-items.json').read_text()))
        self.assertTrue(any(a[1]==state['items'][0]['id'] and a[2]=='NEEDS_EVIDENCE' for a in plan))
    def test_p2_work_preserved_but_not_gating(self):
        state=json.loads((HERE/'handoff/ADOPTION_STATE_TEMPLATE.json').read_text())
        p2=next(x for x in state['items'] if x['id']=='C24')
        p2['status']='partial'
        plan=plan_gaps.plan(state,json.loads((HERE/'contracts/change-items.json').read_text()))
        self.assertTrue(any(a[1]=='C24' and a[0]=='P2_optional' for a in plan))

if __name__=='__main__':unittest.main()
