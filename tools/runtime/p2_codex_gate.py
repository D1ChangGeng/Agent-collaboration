"""Aggregate hashed P2-CODEX scenario evidence without promotion shortcuts."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS = (
    "P2-CODEX-TWO-MACHINE-LOOP", "P2-CODEX-UI-EXIT",
    "P2-CODEX-NETWORK-PARTITION", "P2-CODEX-NODE-RESTART",
    "P2-CODEX-SESSION-REPLACEMENT", "P2-CODEX-ACK-LOSS",
    "P2-CODEX-STALE-OWNER", "P2-CODEX-UNCERTAIN-EFFECT",
)


class GateRejected(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ref(path: Path, root: Path) -> dict:
    absolute = path.resolve(strict=True)
    if not absolute.is_relative_to(root.resolve(strict=True)):
        raise GateRejected("evidence is outside the private run root")
    data = absolute.read_bytes()
    return {"path": str(absolute.relative_to(root)), "sha256": digest(data),
            "size_bytes": len(data)}


def init(output: Path, commit: str, tree: str, machines: Path) -> dict:
    value = load(machines)
    if output.exists() or len(commit) != 40 or len(tree) != 40:
        raise GateRejected("P2-CODEX run identity is invalid")
    if value.get("schema_version") != "acs-p2-machines/1" or len(value.get("machines", [])) != 2:
        raise GateRejected("two current Machine observations are required")
    output.mkdir(mode=0o700, parents=True)
    state = {"schema_version":"acs-p2-codex-gate-run/1", "status":"blocked",
             "source_commit":commit, "source_tree":tree,
             "created_at":datetime.now(UTC).isoformat(), "machines":value["machines"],
             "scenario_order":list(SCENARIOS),
             "scenarios":{name:{"status":"not_run","evidence":[],"unresolved_items":[]}
                          for name in SCENARIOS}, "review":{}, "product_owner_decision":{}}
    (output / "state.json").write_text(json.dumps(state,sort_keys=True,separators=(",",":")))
    (output / "state.json").chmod(0o600)
    return state


def attach(output: Path, scenario: str, evidence: list[Path], status: str,
           unresolved: list[str]) -> dict:
    state_path = output / "state.json"; state = load(state_path)
    if scenario not in SCENARIOS or status not in {"passed","blocked"}:
        raise GateRejected("scenario attachment is invalid")
    current = state["scenarios"][scenario]
    if current["status"] != "not_run" or not evidence or status == "passed" and unresolved:
        raise GateRejected("scenario attachment conflicts with existing state")
    current.update(status=status, evidence=[ref(path,output) for path in evidence],
                   unresolved_items=unresolved, observed_at=datetime.now(UTC).isoformat())
    state["status"] = ("acceptance_ready" if all(
        value["status"] == "passed" for value in state["scenarios"].values()) else "blocked")
    state_path.write_text(json.dumps(state,sort_keys=True,separators=(",",":")))
    state_path.chmod(0o600); return state


def audit(output: Path, commit: str, tree: str) -> dict:
    state = load(output / "state.json")
    if (state.get("schema_version") != "acs-p2-codex-gate-run/1"
            or state.get("source_commit") != commit or state.get("source_tree") != tree
            or tuple(state.get("scenario_order",())) != SCENARIOS
            or set(state.get("scenarios",{})) != set(SCENARIOS)):
        raise GateRejected("P2-CODEX run identity changed")
    for value in state["scenarios"].values():
        if value["status"] not in {"not_run","blocked","passed"}:
            raise GateRejected("scenario status is invalid")
        if value["status"] == "passed" and value["unresolved_items"]:
            raise GateRejected("passing scenario has unresolved items")
        for item in value["evidence"]:
            data = (output / item["path"]).read_bytes()
            if len(data) != item["size_bytes"] or digest(data) != item["sha256"]:
                raise GateRejected("scenario evidence digest differs")
    complete = all(value["status"] == "passed" for value in state["scenarios"].values())
    if (state["status"] == "acceptance_ready") != complete:
        raise GateRejected("aggregate status differs from scenarios")
    return {"valid":True,"status":state["status"],"passed":sum(
        value["status"]=="passed" for value in state["scenarios"].values())}


def main(argv=None):
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="action",required=True)
    a=sub.add_parser("init"); a.add_argument("--output",type=Path,required=True); a.add_argument("--commit",required=True); a.add_argument("--tree",required=True); a.add_argument("--machines",type=Path,required=True)
    b=sub.add_parser("attach"); b.add_argument("--output",type=Path,required=True); b.add_argument("--scenario",required=True); b.add_argument("--status",choices=("passed","blocked"),required=True); b.add_argument("--evidence",type=Path,action="append",required=True); b.add_argument("--unresolved",action="append",default=[])
    c=sub.add_parser("audit"); c.add_argument("--output",type=Path,required=True); c.add_argument("--commit",required=True); c.add_argument("--tree",required=True)
    args=parser.parse_args()
    result = init(args.output,args.commit,args.tree,args.machines) if args.action=="init" else attach(args.output,args.scenario,args.evidence,args.status,args.unresolved) if args.action=="attach" else audit(args.output,args.commit,args.tree)
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__": main()
