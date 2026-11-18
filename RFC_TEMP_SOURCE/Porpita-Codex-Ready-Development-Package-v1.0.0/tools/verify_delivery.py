#!/usr/bin/env python3
"""Check final delivery record/files. Cannot verify truth of screenshots or model use."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]

def required_ids(name: str) -> set[str]:
    return {x["id"] for x in json.loads((PACK / f"contracts/{name}.json").read_text(encoding="utf-8"))["items"]}

def local_file(root: Path, value: str) -> Path | None:
    if not isinstance(value, str) or not value or "://" in value:
        return None
    try:
        p = (root / value).resolve()
        p.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return p if p.is_file() and p.stat().st_size > 0 else None

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def validate_record(record: dict, root: Path, require_accepted: bool = True) -> list[str]:
    e: list[str] = []
    if record.get("schema_version") != "porpita-delivery/1" or record.get("product") != "Porpita":
        e.append("Wrong delivery schema or product")
    if require_accepted and record.get("status") != "PRODUCT_ACCEPTED":
        e.append("Product is not accepted; keep candidate status")
    if record.get("status") == "PRODUCT_ACCEPTED" and record.get("blockers"):
        e.append("Accepted delivery cannot retain blockers")
    for name in ["porpita", "acs", "orca_upstream"]:
        src = record.get("sources", {}).get(name, {})
        if not re.fullmatch(r"[0-9a-f]{40}", str(src.get("commit", ""))):
            e.append(f"Missing actual commit: {name}")
        if src.get("dirty") and not local_file(root, src.get("patch_evidence", "")):
            e.append(f"Dirty source lacks exact patch evidence: {name}")
    artifacts = record.get("artifacts", [])
    installers = [a for a in artifacts if a.get("kind") == "installer" and a.get("target") == record.get("primary_target")]
    if not installers:
        e.append("Missing primary-target installer")
    for a in artifacts:
        p = local_file(root, a.get("path", ""))
        if p is None:
            e.append(f"Artifact unavailable: {a.get('path')}")
        elif file_hash(p) != a.get("sha256"):
            e.append(f"Artifact digest mismatch: {a.get('path')}")
    rows = record.get("scenarios", [])
    seen = [x.get("id") for x in rows]
    if len(seen) != len(set(seen)):
        e.append("Duplicate scenario records")
    by_id = {x.get("id"): x for x in rows}
    for key in sorted(required_ids("acceptance-scenarios")):
        row = by_id.get(key, {})
        if row.get("status") != "pass":
            e.append(f"Required functional scenario not passed: {key}")
        if row.get("simulated") is not False:
            e.append(f"Scenario must not be a simulated final result: {key}")
        if not row.get("environment"):
            e.append(f"Missing actual environment: {key}")
        evidence = row.get("evidence", [])
        if not evidence or any(local_file(root, p) is None for p in evidence):
            e.append(f"Missing/nonlocal/empty scenario evidence: {key}")
    for field, spec in [("functional_coverage", "feature-parity"), ("message_paths", "message-paths"), ("branding", "branding-map")]:
        values = record.get(field, [])
        ids = [x.get("id") for x in values]
        if len(ids) != len(set(ids)):
            e.append(f"Duplicate coverage IDs: {field}")
        indexed = {x.get("id"): x for x in values}
        for key in sorted(required_ids(spec)):
            value = indexed.get(key, {})
            if value.get("status") != "complete" or not value.get("implementation"):
                e.append(f"Incomplete coverage: {field}/{key}")
            proof = value.get("evidence", [])
            if not proof or any(local_file(root, path) is None for path in proof):
                e.append(f"Missing coverage evidence: {field}/{key}")
    return e

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--delivery-root", type=Path)
    a = p.parse_args()
    root = (a.delivery_root or a.manifest.parent).resolve()
    try:
        record = json.loads(a.manifest.read_text(encoding="utf-8"))
        errors = validate_record(record, root)
        try:
            import jsonschema
        except ImportError:
            print("Note: optional full JSON Schema validation unavailable; core file/record checks still run.")
        else:
            schema = json.loads((PACK / "contracts/delivery-manifest.schema.json").read_text(encoding="utf-8"))
            errors.extend(f"Schema: {err.message}" for err in jsonschema.Draft202012Validator(schema).iter_errors(record))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Cannot validate delivery: {exc}")
        return 2
    if errors:
        print("DELIVERY RECORD NOT COMPLETE\n" + "\n".join(errors))
        return 1
    print("DELIVERY RECORD/FILES CONSISTENT. A human must still verify actual application and model evidence.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
