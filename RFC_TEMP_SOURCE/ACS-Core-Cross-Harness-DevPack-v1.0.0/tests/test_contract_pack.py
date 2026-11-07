"""Package tests only; fixture success never proves target runtime qualification."""
from __future__ import annotations
import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from validate_pack import check_pack
from validate_trace import TraceViolation, validate_trace

def load(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))

class PackageTests(unittest.TestCase):
    def test_package_consistency(self):
        result=check_pack();self.assertTrue(result['passed'],result['issues'])
    def test_forty_requirements(self):self.assertEqual(len(load('contracts/requirements.json')['requirements']),40)
    def test_all_scenarios_are_unexecuted_specs(self):
        scenarios=load('tests/scenarios.json')['scenarios'];self.assertEqual(len(scenarios),96)
        self.assertTrue(all(x['status']=='not_executed' for x in scenarios))
    def test_ui_features_have_owners(self):
        ui=load('contracts/ui-feature-matrix.json')['features'];self.assertEqual(len(ui),30)
        self.assertTrue(all(x['authority'] and x['degradation'] for x in ui))
    def test_no_false_implementation_claim(self):
        self.assertFalse(load('handoff/ui-readiness.json')['core_contract_ready'])
        self.assertEqual(load('handoff/implementation-ledger.json')['status'],'not_started')
    def test_mcp_defaults(self):
        c=load('contracts/legacy-mcp-compatibility.json')
        self.assertEqual(c['retained_send_defaults'],{'activation':'invoke','response_mode':'async'})
    def test_source_snapshots_are_not_deployment_attestations(self):
        self.assertEqual(load('sources/source-lock.json')['status'],'reference_snapshot_not_deployment_attestation')
    def test_unknown_is_not_directly_retryable(self):
        edges=load('contracts/delivery-transitions.json')['edges']
        self.assertFalse(any(e['from']=='unknown' and e['to']=='queued' for e in edges))
    def test_adapter_protocol_imports(self):
        spec=importlib.util.spec_from_file_location('pack_adapter',ROOT/'contracts/adapter_protocol.py')
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        self.assertTrue(hasattr(module,'HarnessAdapter'))

class TraceTests(unittest.TestCase):
    def test_reply_is_independent_of_native_unknown(self):validate_trace(load('fixtures/traces/valid_unknown_with_reply.json'))
    def test_invalid_traces_are_rejected(self):
        for path in (ROOT/'fixtures/traces').glob('invalid_*.json'):
            with self.subTest(path=path.name),self.assertRaises(TraceViolation):validate_trace(json.loads(path.read_text()))
    def test_no_handoff_without_intent(self):
        with self.assertRaises(TraceViolation):validate_trace([{'type':'handoff','operation':'unrecorded','epoch':1}])
    def test_evidence_required_for_claimed_admission(self):
        t=load('fixtures/traces/valid_unknown_with_reply.json');t[4]['state']='accepted'
        with self.assertRaises(TraceViolation):validate_trace(t)
    def test_proved_native_replay_same_scope(self):
        t=load('fixtures/traces/valid_unknown_with_reply.json');t.append({'type':'handoff','operation':'op1','epoch':1,'replay_safe':True,'dedup_scope':'scope1','replay_evidence_ref':'synthetic-native-contract'})
        validate_trace(t)
    def test_native_replay_wrong_scope_rejected(self):
        t=load('fixtures/traces/valid_unknown_with_reply.json');t.append({'type':'handoff','operation':'op1','epoch':1,'replay_safe':True,'dedup_scope':'scope2','replay_evidence_ref':'synthetic'})
        with self.assertRaises(TraceViolation):validate_trace(t)
    def test_wait_timeout_no_side_effect(self):validate_trace([{'type':'wait_timeout','resend':False,'cancel_peer':False}])
    def test_wait_timeout_cannot_cancel(self):
        with self.assertRaises(TraceViolation):validate_trace([{'type':'wait_timeout','cancel_peer':True}])
    def test_binding_never_regresses(self):
        with self.assertRaises(TraceViolation):validate_trace([{'type':'binding','receiver':'r','epoch':2},{'type':'binding','receiver':'r','epoch':1}])
    def test_immutable_message_identity(self):
        t=load('fixtures/traces/valid_unknown_with_reply.json');m=copy.deepcopy(t[1]);m['sender']='slot:C';t.append(m)
        with self.assertRaises(TraceViolation):validate_trace(t)

if __name__=='__main__':unittest.main()
