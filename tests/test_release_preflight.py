"""A frozen release must never borrow CI from another commit or ignore failures."""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'scripts/release_preflight.py'
SPEC = importlib.util.spec_from_file_location('release_preflight', PATH)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class CandidateCiTests(unittest.TestCase):
    def run_record(self, sha='candidate', conclusion='success', status='completed'):
        return {'headSha': sha, 'workflowName': 'Validate ACS', 'status': status,
                'conclusion': conclusion, 'databaseId': 42}

    def test_other_commits_do_not_qualify_the_candidate(self):
        with self.assertRaises(ValueError):
            preflight.verify_ci([self.run_record(sha='other')], 'candidate')

    def test_current_failure_is_not_hidden_by_one_success(self):
        with self.assertRaises(ValueError):
            preflight.verify_ci([self.run_record(), self.run_record(conclusion='failure')], 'candidate')

    def test_pending_run_cannot_be_published(self):
        with self.assertRaises(ValueError):
            preflight.verify_ci([self.run_record(status='in_progress', conclusion=None)], 'candidate')

    def test_completed_exact_candidate_is_qualified(self):
        self.assertEqual(preflight.verify_ci([self.run_record(), self.run_record(sha='other')], 'candidate'), [42])
