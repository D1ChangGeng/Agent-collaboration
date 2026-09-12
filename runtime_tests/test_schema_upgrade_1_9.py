from __future__ import annotations

import unittest

from runtime.schema_upgrade import (
    FROM_SCHEMA_CHECKSUM,
    FROM_SCHEMA_VERSION,
    REQUIRED_BASE_TABLES,
    TO_SCHEMA_VERSION,
    apply_candidate_schema,
    schema_bytes,
    schema_sha256,
)


class FakeCursor:
    def __init__(self, version="1.8", checksum=FROM_SCHEMA_CHECKSUM):
        self.version = version
        self.checksum = checksum
        self.rows = []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if isinstance(statement, bytes):
            self.rows = []
        elif "unnest" in statement:
            self.rows = [(name, name) for name in REQUIRED_BASE_TABLES]
        elif "SELECT schema_version" in statement:
            self.rows = [(self.version, self.checksum)]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, version="1.8", checksum=FROM_SCHEMA_CHECKSUM):
        self.value = FakeCursor(version, checksum)

    def cursor(self):
        return self.value


class MigrationHelperTests(unittest.TestCase):
    def test_version_sequence_is_receiver_18_to_recovery_19(self):
        self.assertEqual((FROM_SCHEMA_VERSION, TO_SCHEMA_VERSION), ("1.8", "1.9"))
        connection = FakeConnection()
        checksum = "a" * 64
        self.assertEqual(
            apply_candidate_schema(connection, integrated_schema_checksum=checksum),
            schema_sha256(),
        )
        self.assertIn((
            ("UPDATE runtime_schema_metadata SET schema_version=%s,schema_checksum=%s "
             "WHERE schema_name=%s"),
            ("1.9", checksum, "acs-p1-runtime"),
        ), connection.value.executed)

    def test_wrong_predecessor_or_missing_checksum_fails_before_schema(self):
        for connection, checksum in ((FakeConnection("1.7"), "a" * 64),
                                     (FakeConnection("1.8"), None),
                                     (FakeConnection("1.8", "8" * 64), "a" * 64)):
            with self.subTest(version=connection.value.version, checksum=checksum):
                with self.assertRaises(RuntimeError):
                    apply_candidate_schema(
                        connection, integrated_schema_checksum=checksum,
                    )
                self.assertFalse(any(statement == schema_bytes()
                                     for statement, _ in connection.value.executed))

    def test_standalone_fixture_applies_without_runtime_metadata_mutation(self):
        connection = FakeConnection("unrelated")
        self.assertEqual(
            apply_candidate_schema(connection, standalone_fixture=True), schema_sha256(),
        )
        self.assertTrue(any(statement == schema_bytes()
                            for statement, _ in connection.value.executed))
        self.assertFalse(any(
            isinstance(statement, str) and "UPDATE runtime_schema_metadata" in statement
            for statement, _ in connection.value.executed
        ))

    def test_exact_19_repeat_is_safe_and_changed_checksum_fails(self):
        checksum = "9" * 64
        repeated = FakeConnection("1.9", checksum)
        self.assertEqual(
            apply_candidate_schema(repeated, integrated_schema_checksum=checksum),
            schema_sha256(),
        )
        self.assertTrue(any(statement == schema_bytes()
                            for statement, _ in repeated.value.executed))
        changed = FakeConnection("1.9", "a" * 64)
        with self.assertRaises(RuntimeError):
            apply_candidate_schema(changed, integrated_schema_checksum=checksum)
        self.assertFalse(any(statement == schema_bytes()
                             for statement, _ in changed.value.executed))


if __name__ == "__main__":
    unittest.main()
