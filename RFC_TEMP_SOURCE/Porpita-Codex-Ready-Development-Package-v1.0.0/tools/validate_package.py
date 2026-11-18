#!/usr/bin/env python3
"""Offline consistency checks for this specification package, not Porpita tests."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

def load(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding="utf-8"))

def validate(root: Path, check_hashes: bool = True) -> list[str]:
    errors: list[str] = []
    names = ["requirements", "feature-parity", "acceptance-scenarios", "message-paths", "branding-map", "work-packages"]
    data = {}
    for name in names:
        try:
            items = load(root, f"contracts/{name}.json")["items"]
            ids = [x["id"] for x in items]
            if len(ids) != len(set(ids)):
                errors.append(f"Duplicate IDs: {name}")
            data[name] = {x["id"]: x for x in items}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"Cannot read {name}: {exc}")
    if len(data) != len(names):
        return errors
    work = data["work-packages"]
    tests = data["acceptance-scenarios"]
    sources = load(root, "contracts/source-lock.json")["sources"]
    source_ids = {x["id"] for x in sources}
    for family in ["requirements", "feature-parity", "message-paths"]:
        for key, item in data[family].items():
            if item["owner"] not in work:
                errors.append(f"Unknown work owner {key}")
            for test in item["acceptance"]:
                if test not in tests:
                    errors.append(f"Unknown acceptance {key}: {test}")
    for key, item in tests.items():
        if item["owner"] not in work:
            errors.append(f"Unknown scenario owner: {key}")
    visiting, visited = set(), set()
    def visit(key: str):
        if key in visiting:
            errors.append(f"Work dependency cycle at {key}")
            return
        if key in visited:
            return
        visiting.add(key)
        for dep in work[key]["depends_on"]:
            if dep not in work:
                errors.append(f"Unknown dependency {key}: {dep}")
            else:
                visit(dep)
        visiting.remove(key)
        visited.add(key)
    for key, item in work.items():
        visit(key)
        if not (root / f"tasks/{key}.md").is_file():
            errors.append(f"Missing task file: {key}")
        for sid in item["sources"]:
            if sid not in source_ids:
                errors.append(f"Unknown source {key}: {sid}")
        for rid in item["requirements"]:
            if rid not in data["requirements"] or data["requirements"][rid]["owner"] != key:
                errors.append(f"Invalid requirement assignment {key}: {rid}")
    for rel in ["README.md", "START_HERE_CODEX.md", "AGENTS.md", "contracts/desktop-boundary.ts", "contracts/delivery-manifest.schema.json"]:
        if not (root / rel).is_file():
            errors.append(f"Missing entry: {rel}")
    for file in root.rglob("*.json"):
        try:
            json.loads(file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            errors.append(f"Invalid JSON {file.relative_to(root)}: {exc}")
    # Only actual Markdown links, not code examples or hypothetical output paths.
    for file in root.rglob("*.md"):
        text = file.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", text):
            if re.match(r"^[a-zA-Z][\w+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (file.parent / path).exists():
                errors.append(f"Broken local link {file.relative_to(root)}: {target}")
    manifest = root / "PACKAGE-MANIFEST.json"
    if check_hashes and manifest.exists():
        expected = load(root, "PACKAGE-MANIFEST.json")["files"]
        for item in expected:
            path = root / item["path"]
            if not path.is_file():
                errors.append(f"Missing manifest file: {item['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                errors.append(f"Hash mismatch: {item['path']}")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-hashes", action="store_true")
    args = parser.parse_args()
    errors = validate(args.root.resolve(), not args.skip_hashes)
    if errors:
        print("PACKAGE CHECK FAILED\n" + "\n".join(errors))
        return 1
    print("PACKAGE CONSISTENT — specification checks only; no product acceptance is implied.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
