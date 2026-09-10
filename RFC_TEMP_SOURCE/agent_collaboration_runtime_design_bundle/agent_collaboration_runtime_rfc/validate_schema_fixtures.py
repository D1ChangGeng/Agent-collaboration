"""Validate design schemas and synthetic fixtures; does not test a runtime."""
from pathlib import Path
import copy
import json
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
pairs = [
    ("collaboration-packet.schema.json", "example-packet.json"),
    ("capability-observation.schema.json", "example-capability-observation.json"),
    ("command.schema.json", "example-command.json"),
]
loaded = []
for schema_name, example_name in pairs:
    schema = json.loads((ROOT / schema_name).read_text(encoding="utf-8"))
    example = json.loads((ROOT / example_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(example)
    loaded.append((validator, example))

negative = []
bad = copy.deepcopy(loaded[0][1]); bad["provider"] = "user_relay"
negative.append((loaded[0][0], bad))
bad = copy.deepcopy(loaded[0][1]); del bad["task"]["accepted_state"]
negative.append((loaded[0][0], bad))
bad = copy.deepcopy(loaded[0][1]); bad["type"] = "unversioned_custom_type"
negative.append((loaded[0][0], bad))
bad = copy.deepcopy(loaded[1][1]); bad["state"] = "confirmed"
negative.append((loaded[1][0], bad))
bad = copy.deepcopy(loaded[1][1]); bad["state"] = "supported"
negative.append((loaded[1][0], bad))
bad = copy.deepcopy(loaded[2][1]); bad["target"]["expected_revision"] = -1
negative.append((loaded[2][0], bad))
bad = copy.deepcopy(loaded[2][1]); del bad["idempotency_key"]
negative.append((loaded[2][0], bad))
for validator, instance in negative:
    if not list(validator.iter_errors(instance)):
        raise AssertionError("An invalid synthetic fixture unexpectedly passed.")
print("PASS: 3 schema/example pairs and 7 negative fixtures.")
print("NOT RUN: real Harness, network, recovery, authorization and side-effect tests.")
