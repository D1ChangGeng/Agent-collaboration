"""Tests of specification tools only. Synthetic records are never product evidence."""
from __future__ import annotations
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(obj)
    return obj
pack = module("validate_package")
delivery = module("verify_delivery")

class PackageTests(unittest.TestCase):
    def test_package_consistency(self):
        self.assertEqual(pack.validate(ROOT, check_hashes=False), [])

    def test_template_is_not_product_acceptance(self):
        value = json.loads((ROOT / "handoff/DELIVERY_MANIFEST.template.json").read_text())
        self.assertTrue(delivery.validate_record(value, ROOT))
        self.assertEqual(value["status"], "NOT_RUN")

    def test_source_references_are_pinned(self):
        value = json.loads((ROOT / "contracts/source-lock.json").read_text())
        for repo in value["repositories"].values():
            self.assertRegex(repo["ref"], r"^[a-f0-9]{40}$")

    def test_existing_and_new_protocol_are_distinguished(self):
        text = (ROOT / "contracts/desktop-boundary.ts").read_text()
        self.assertIn("not an adopted ACS wire protocol", text)
        self.assertIn('readonly backend: CommunicationBackend', text)

    def test_message_cutover_has_no_fallback(self):
        value = json.loads((ROOT / "contracts/message-paths.json").read_text())
        self.assertEqual(value["default_backend"], "acs")
        self.assertFalse(value["fallback_to_upstream_messaging"])

    def test_brand_preserves_legal_and_wire(self):
        rows = json.loads((ROOT / "contracts/branding-map.json").read_text())["items"]
        self.assertTrue(any(x["action"] == "retain_legal" for x in rows))
        self.assertTrue(any(x["action"] == "retain_compatibility" for x in rows))

    def sample(self, root):
        # Explicit synthetic input to validator unit test, never shipped as acceptance evidence.
        (root / "evidence.txt").write_text("synthetic test fixture, not an actual app run")
        (root / "candidate.exe").write_bytes(b"not an executable; validator unit-test fixture")
        def coverage(spec):
            return [{"id":i,"status":"complete","implementation":"unit-test-only","evidence":["evidence.txt"]}
                    for i in sorted(delivery.required_ids(spec))]
        return {"schema_version":"porpita-delivery/1","product":"Porpita","product_version":"0.1.0",
            "status":"PRODUCT_ACCEPTED","primary_target":"windows-x64",
            "sources":{n:{"commit":"a"*40,"dirty":False} for n in ["porpita","acs","orca_upstream"]},
            "artifacts":[{"kind":"installer","path":"candidate.exe","sha256":delivery.file_hash(root/"candidate.exe"),"target":"windows-x64","signing":"unsigned_internal_candidate"}],
            "scenarios":[{"id":i,"status":"pass","environment":"unit-test-only","simulated":False,"evidence":["evidence.txt"]} for i in sorted(delivery.required_ids("acceptance-scenarios"))],
            "functional_coverage":coverage("feature-parity"),"message_paths":coverage("message-paths"),"branding":coverage("branding-map"),"limitations":[],"blockers":[]}

    def test_record_validator_positive_structure_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root)
            self.assertEqual(delivery.validate_record(value,root),[])
            try: import jsonschema
            except ImportError: return
            schema=json.loads((ROOT/'contracts/delivery-manifest.schema.json').read_text())
            jsonschema.Draft202012Validator(schema).validate(value)

    def test_record_rejects_missing_required_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root); value["scenarios"].pop()
            self.assertTrue(delivery.validate_record(value,root))

    def test_record_rejects_simulated_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root); value["scenarios"][0]["simulated"]=True
            self.assertTrue(any('simulated' in x for x in delivery.validate_record(value,root)))

    def test_record_rejects_mismatched_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root); value["artifacts"][0]["sha256"]='0'*64
            self.assertTrue(any('digest' in x for x in delivery.validate_record(value,root)))

    def test_record_rejects_path_escape_and_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root)
            value['scenarios'][0]['evidence']=['../outside.txt']
            value['sources']['acs']['commit']=''
            errors=delivery.validate_record(value,root)
            self.assertTrue(any('evidence' in x for x in errors))
            self.assertTrue(any('commit' in x for x in errors))

    def test_record_rejects_blockers_and_duplicate_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); value=self.sample(root)
            value['blockers']=['actual Host not connected']
            value['message_paths'].append(copy.deepcopy(value['message_paths'][0]))
            errors=delivery.validate_record(value,root)
            self.assertTrue(any('blockers' in x for x in errors))
            self.assertTrue(any('Duplicate' in x for x in errors))

if __name__ == '__main__':
    unittest.main()
