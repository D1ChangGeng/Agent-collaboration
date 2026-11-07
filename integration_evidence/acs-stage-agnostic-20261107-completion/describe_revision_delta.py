from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
baseline = json.loads((OUT / "p0-p1-current.json").read_text())["fixed_before"]
path = ROOT / "runtime/communication_http.py"
after = path.read_bytes()
new = b'                            offset=offset, max_inline_bytes=maximum,\n                            **({"include_native_source": True} if include == "true" else {}))'
old = b'                            offset=offset, max_inline_bytes=maximum, include_native_source=include == "true")'
assert after.count(new) == 1
before = after.replace(new, old)
assert hashlib.sha256(before).hexdigest() == baseline["runtime/communication_http.py"]
patch = "".join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
                                  fromfile="a/runtime/communication_http.py", tofile="b/runtime/communication_http.py"))
(OUT / "runtime-change.diff").write_text(patch, encoding="utf-8")
result = {"schema_version": "acs-source-impact-review/1", "file": "runtime/communication_http.py",
    "before_sha256": hashlib.sha256(before).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest(),
    "reverse_patch_matches_captured_before": True,
    "behavior_delta": "Only explicit include_native_source=true forwards the extension keyword. Default/false retain legacy read_message(offset,max_inline_bytes) call shape.",
    "affected_verification": ["read-compatibility-final", "p0-p1-final"],
    "Native_E4_retention_reason": "The actual E4 path uses Project/MCP calls and the signed receiver API, not this communication HTTP read facade. All other captured Runtime/deployment bytes in e match; this change neither admits Native input nor creates an explicit reply.",
    "migration": None, "new_dependency": None}
(OUT / "source-impact-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"reverse_patch_matches_captured_before": True, "before": result["before_sha256"], "after": result["after_sha256"]}))
