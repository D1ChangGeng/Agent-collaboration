"""Generate the review views of the Porpita UI catalog. Structural checks only."""
import argparse
import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

PACKAGE = Path(__file__).resolve().parents[1]
CATALOG = PACKAGE / "catalog"
INDEX = PACKAGE / "source-index"
REFERENCE_HEAD = "517555d5ce68ba8e417cdd2192b561a4061237ef"
INSTALLED_TREE = "2c1447f1e54c9deed41af5108a7f402d429e5c9a"

def read(path):
    return path.read_text(encoding="utf-8-sig")

def dump(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")

def rows_csv(path, headers, values):
    # BOM keeps Chinese legible in Windows spreadsheet readers.
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(values)

def compact(text):
    return text.replace("|", "&#124;").replace("\n", " ")

def md_links(source, links):
    return ", ".join(
        f"[{path.rsplit('/',1)[-1]}](<{source.as_posix()}/{quote(path, safe='/')}>)"
        for path in links
    )

def audit_module_routes(route_file, rows, candidates, errors):
    routes = {}
    paths = {candidate["path"] for candidate in candidates}
    for line in read(CATALOG / route_file).splitlines():
        if not line or line.startswith("#"):
            continue
        path, target, reason = line.split("|")
        if path in routes or path not in paths:
            errors.append(f"Invalid reviewed module route: {path}")
        ids = target.split(",") if target != "—" else []
        if set(ids) - rows.keys():
            errors.append(f"Reviewed module route has unknown rows: {target}")
        routes[path] = (";".join(ids), reason)
    return routes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--history", type=Path, help="Checkout holding the original Candidate 11 evidence archive")
    args = parser.parse_args()
    source = args.source.resolve()
    history = args.history.resolve() if args.history else source
    if not (source / "src/renderer/src/App.tsx").is_file():
        parser.error("--source must point to the Porpita checkout")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()

    name_index = defaultdict(list)
    for directory in ("src", "docs", "tests/e2e"):
        for path in (source / directory).rglob("*"):
            if path.is_file():
                name_index[path.name].append(path.relative_to(source).as_posix())

    journeys = set(re.findall(r"\| (J\d\d) ", read(PACKAGE / "PLAYBACK_SCENARIOS.md")))
    rows = {}
    errors = []
    for path in sorted(CATALOG.glob("*.psv")):
        for n, line in enumerate(read(path).splitlines(), start=1):
            if not line or line.startswith("#"):
                continue
            parts = [s.strip() for s in line.split("|")]
            if len(parts) != 7 or not all(parts):
                errors.append(f"{path.name}:{n}: expected seven nonempty fields")
                continue
            id_, label, anchors, current, action, target, replay = parts
            if id_ in rows:
                errors.append(f"duplicate ID {id_}")
            if not re.fullmatch(r"[A-T](?:\.[a-zA-Z0-9-]+)*", id_):
                errors.append(f"{id_}: invalid ID")
            if action not in {"保留", "改造", "新增"}:
                errors.append(f"{id_}: unknown disposition {action}")
            anchor_paths = []
            for anchor in anchors.split(","):
                if "/" in anchor:
                    if (source / anchor).exists():
                        anchor_paths.append(anchor)
                    else:
                        errors.append(f"{id_}: source path missing {anchor}")
                else:
                    hits = name_index.get(anchor, [])
                    if len(hits) != 1:
                        errors.append(f"{id_}: {anchor} resolved to {hits}")
                    else:
                        anchor_paths.extend(hits)
            checks = replay.split(",")
            if set(checks) - journeys:
                errors.append(f"{id_}: unregistered replay {set(checks)-journeys}")
            rows[id_] = dict(id=id_, title=label, paths=anchor_paths, current=current,
                             decision=action, target=target, journeys=checks)
    overlay_members = {"O.modal", "O.overlay", "O.local", "O.native"}
    for id_, row in rows.items():
        parent = id_.rsplit(".", 1)[0] if "." in id_ else ""
        if parent in overlay_members:
            parent = "O"
        if parent and parent not in rows:
            errors.append(f"{id_}: parent {parent} missing")
        row["parent"] = parent

    summary = json.loads(read(INDEX / "summary.json"))
    for entry in summary["registry"]["setting"]:
        if "N."+entry["id"] not in rows:
            errors.append(f"Settings renderer has no row: {entry['id']}")
    setting_nav = read(source / "src/renderer/src/lib/settings-navigation-types.ts")
    settings = re.search(r"const SETTINGS_NAV_TARGETS = \[(.*?)\]", setting_nav, re.S)
    for target in re.findall(r"'([^']+)'", settings.group(1)):
        if "N."+target not in rows:
            errors.append(f"Settings navigation has no row: {target}")
    for key in ("modal", "notice"):
        for entry in summary["registry"][key]:
            if "O."+entry["id"] not in rows:
                errors.append(f"Root surface has no row: {entry['id']}")
    views = dict(terminal="D", settings="N", skills="L.03", artifacts="L.04",
                 tasks="J", automations="L.01", activity="C.07", space="M.02", mobile="M.01")
    docks = {"explorer":"G.02", "source-control":"G.03", "checks":"G.04", "ports":"G.05",
             "vault":"G.06", "workspaces":"G.07", "pr-checks":"G.07"}
    for key, mapping in (("activeView", views), ("rightDock", docks)):
        for entry in summary["registry"][key]:
            if mapping.get(entry["id"]) not in rows:
                errors.append(f"{key} without row: {entry['id']}")
    primitives = {
        "accordion":"P.09","badge":"P.08","button":"P.01","button-group":"P.01","card":"P.08",
        "checkbox":"P.07","collapsible":"P.09","color-picker":"P.07","command":"P.03",
        "context-menu":"P.04","dialog":"P.06","dropdown-menu":"P.04","hover-card":"P.05",
        "input":"P.02","label":"P.02","popover":"P.05","progress":"P.08","radio-group":"P.07",
        "repo-multi-combobox":"P.03","scroll-area":"P.10","security-surface":"P.06","select":"P.03",
        "separator":"P.09","sheet":"P.06","slider":"P.07","sonner":"P.11","switch":"P.07",
        "tabs":"P.09","textarea":"P.02","toggle":"P.01","toggle-group":"P.01","tooltip":"P.05"
    }
    for path in (source / "src/renderer/src/components/ui").glob("*.tsx"):
        if "." in path.stem:
            continue
        if primitives.get(path.stem) not in rows:
            errors.append(f"Primitive without row: {path.stem}")

    evidence_catalog = json.loads(read(PACKAGE / "evidence" / "observations.json"))
    evidence_by_row = defaultdict(list)
    evidence_ids = set()
    for ev in evidence_catalog:
        if ev["id"] in evidence_ids:
            errors.append(f"Duplicate evidence ID {ev['id']}")
        evidence_ids.add(ev["id"])
        for row_id in ev["rows"]:
            if row_id not in rows:
                errors.append(f"Evidence {ev['id']}: unknown row {row_id}")
            evidence_by_row[row_id].append(ev)
        if ev["kind"] in {"observed", "current-build", "iteration-build", "captured"}:
            path = PACKAGE / "evidence" / ev["path"]
            if not path.is_file():
                errors.append(f"Evidence {ev['id']}: missing {path.name}")
            else:
                record = json.loads(read(path))
                image = record.get("imageFile")
                if not image or not (path.parent / image).is_file():
                    errors.append(f"Evidence {ev['id']}: missing referenced frame")
        elif ev["kind"] == "historical":
            if not (history / ev["path"]).is_file():
                errors.append(f"Evidence {ev['id']}: missing historical artifact")
        elif ev["kind"] in {"fixture", "trial"}:
            if not (PACKAGE / "evidence" / ev["path"]).is_file():
                errors.append(f"Evidence {ev['id']}: missing fixture or trial capture")
        else:
            errors.append(f"Evidence {ev['id']}: unexpected kind")
    baseline = {}
    for line in read(CATALOG / "baseline-assurance.txt").splitlines():
        if not line or line.startswith("#"):
            continue
        row_id, result, criterion, refs = line.split("|")
        if row_id not in rows or row_id in baseline:
            errors.append(f"Baseline result has unknown or duplicate row: {row_id}")
        if result not in {"局部通过", "发现缺口", "观察待判", "有历史与夹具"}:
            errors.append(f"Baseline result {row_id} has unknown disposition: {result}")
        if not set(refs.split(",")) <= evidence_ids:
            errors.append(f"Baseline result {row_id} has unknown evidence: {refs}")
        baseline[row_id] = (result, criterion + "（" + refs.replace(",", "、") + "）")

    iteration = {}
    for path in sorted(CATALOG.glob("iteration-*-assurance.txt")):
        seen = set()
        for line in read(path).splitlines():
            if not line or line.startswith("#"):
                continue
            row_id, design, source_state, result, criterion, refs = line.split("|")
            if row_id not in rows or row_id in seen:
                errors.append(f"{path.name} has unknown or duplicate row: {row_id}")
            seen.add(row_id)
            if result not in {"本轮局部通过", "夹具通过，集成待验", "现版通过，目标待验", "待验"}:
                errors.append(f"Invalid iteration result for {row_id}: {result}")
            assigned = {item["id"] for item in evidence_by_row[row_id]}
            if refs != "—" and not set(refs.split(",")) <= assigned:
                errors.append(f"Iteration result {row_id} cites unassigned evidence: {refs}")
            iteration[row_id] = (
                design, source_state, result, criterion + ("" if refs == "—" else "（" + refs.replace(",", "、") + "）")
            )
    candidates = [json.loads(line) for line in read(INDEX/"renderer.jsonl").splitlines() if line]
    module_routes = audit_module_routes("module-routes.txt", rows, candidates, errors)
    native_candidates = [
        json.loads(line) for line in read(INDEX / "native-host-candidates.jsonl").splitlines() if line
    ]
    native_routes = audit_module_routes("native-routes.txt", rows, native_candidates, errors)
    for candidate in native_candidates:
        if candidate["path"] not in native_routes:
            errors.append(f"Native host candidate without review route: {candidate['path']}")
    if errors:
        raise SystemExit("\n".join(errors))

    evidence_counts = Counter()
    for row in rows.values():
        ev = evidence_by_row[row["id"]]
        kind = ("本轮构建已回放局部" if any(e["kind"] == "iteration-build" for e in ev) else
                "当前构建已观察局部" if any(e["kind"] == "current-build" for e in ev) else
                "安装版已观察局部" if any(e["kind"] == "observed" for e in ev) else
                "源码组件预览" if any(e["kind"] == "fixture" for e in ev) else
                "设计试验" if any(e["kind"] == "trial" for e in ev) else
                "有捕获待查看" if any(e["kind"] == "captured" for e in ev) else
                "历史记录" if ev else "源映射")
        row["evidence_state"] = kind
        evidence_counts[kind] += 1
        row["evidence"] = [e["id"] for e in ev]
        row["baseline_result"], row["baseline_criterion"] = baseline.get(row["id"], ("未判定", ""))
        defaults = (
            "继承规范" if row["decision"] == "保留" else "目标草案",
            "既有实现可定位" if row["decision"] != "新增" else "目标未接入",
            "待验",
            "按 " + "、".join(row["journeys"]) + " 回放本行涉及的条件与动作"
        )
        row["spec"], row["implementation"], row["acceptance"], row["next_check"] = iteration.get(
            row["id"], defaults
        )

    domains = [v for k,v in rows.items() if "." not in k]
    order = {r["id"]:i for i,r in enumerate(domains)}
    sorted_rows = sorted(rows.values(), key=lambda r:(order[r["id"].split(".")[0]],r["id"]))
    inv = ["# UI Inventory", "", f"当前覆盖模型：{len(domains)} 个功能域，{len(rows)} 个设计条目。"
           "现有界面与待新增对象分开标注；组件族按实际用途合并。每条现状、范围、状态和回放证据见 [Coverage Matrix](COVERAGE_MATRIX.md)。",
           "", "来源：实际 Porpita 应用、入口与深链接、静态渲染/事件索引和原生 Electron surfaces；以 [源索引](source-index/README.md) 继续反查遗漏。", ""]
    matrix = ["# UI SPEC Coverage Matrix", "",
              f"Porpita 源码锚点使用当前工作树，HEAD 为 `{head}`。Windows 0.1.0 候选 11 的交付源树为 `{INSTALLED_TREE}`。"
              "各开发构建和试验的身份见 [来源](SOURCE_BASELINE.md)。", "",
              "首轮判定保留当时的事实。本轮分别记录设计、源码进度与验证范围。局部通过只覆盖列明的条件，后续场景见 [回放](PLAYBACK_SCENARIOS.md)。", "",
              "横向筛选与批次跟踪使用 [CSV](coverage-matrix.csv)。基础组件/动效规则见 [视觉与交互](VISUAL_INTERACTION_SYSTEM.md)。", ""]
    for domain in domains:
        id_ = domain["id"]
        group = [r for r in sorted_rows if r["id"] == id_ or r["id"].startswith(id_+".")]
        inv += [f"## {id_} · {domain['title']}", ""]
        for row in group:
            if row["id"] != id_:
                indent = "  " if row["parent"] not in {"", id_} else ""
                scope = "（目标新增）" if row["decision"] == "新增" else ""
                inv.append(f"{indent}- `{row['id']}` {row['title']}{scope}")
        inv += [""]
        matrix += [f"## {id_} · {domain['title']}", "",
                   "| ID / 对象 | 源码 | 现有实现 | 处置 / 目标 | 局部证据 | 首轮判定 | 设计 / 源码状态 | 本轮验收与下一步 | 回放 |",
                   "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for row in group:
            evidence = row["evidence_state"] + (": " + ", ".join(row["evidence"]) if row["evidence"] else "")
            fields = (f"`{row['id']}` {row['title']}",md_links(source,row["paths"]),row["current"],
                      f"**{row['decision']}** · {row['target']}",evidence,
                      row["baseline_result"] + (" · " + row["baseline_criterion"] if row["baseline_criterion"] else ""),
                      row["spec"] + " / " + row["implementation"],
                      row["acceptance"] + " · " + row["next_check"], ", ".join(row["journeys"]))
            matrix.append("| " + " | ".join(map(compact,fields)) + " |")
        matrix += [""]
    dump(PACKAGE / "UI_INVENTORY.md", "\n".join(inv)+"\n")
    dump(PACKAGE / "COVERAGE_MATRIX.md", "\n".join(matrix)+"\n")
    rows_csv(PACKAGE / "coverage-matrix.csv",
             ("ID", "父项", "界面", "源码路径", "现有实现", "处置", "目标规范",
              "局部证据状态", "证据ID", "首轮判定", "首轮条件", "SPEC状态", "源码状态", "本轮验收", "验证范围与下一步", "回放"),
             ([r["id"],r["parent"],r["title"],"; ".join(r["paths"]),r["current"],r["decision"],
               r["target"],r["evidence_state"],"; ".join(r["evidence"]),r["baseline_result"],r["baseline_criterion"],r["spec"],
               r["implementation"],r["acceptance"],r["next_check"],
               "; ".join(r["journeys"])] for r in sorted_rows))

    anchors = defaultdict(list)
    for r in sorted_rows:
        for p in r["paths"]:
            anchors[p].append(r["id"])
    # A directory route is a queue for the owning SPEC, not a reviewed leaf.
    # Do not promote this association to the row's implementation or acceptance evidence.
    components = "src/renderer/src/components/"
    domains_for_directory = {
        "activity":"C.07", "agent":"F.03", "agent-session-continuation":"E.01",
        "agent-workspace-trust":"E.09", "artifacts":"L.04", "automations":"L.01",
        "browser-pane":"I", "cmd-j":"C.09", "collaboration":"K", "contextual-tours":"B.05",
        "crash-report":"O.02", "dashboard":"M.03", "dashboard-popout":"M.03", "dictation":"O.04",
        "diff-comments":"H.05", "dismiss":"O", "editor":"H", "emulator-pane":"I",
        "error-boundaries":"A.04", "feature-tips":"B.05", "feature-wall":"B.05",
        "file-actions":"H.06", "floating-terminal":"D.06", "github":"J.02",
        "github-item-dialog":"J.02", "github-project":"J.02", "gitlab":"J.03",
        "gitlab-item-dialog":"J.03", "host-picker":"M.05", "icons":"P.12",
        "integrations":"N.integrations", "link-actions":"H.06", "machine-identity":"M.05",
        "macos-update-requirement":"O.02", "maintenance":"O.02", "managed-runtime":"M.05",
        "mobile":"M.01", "native-chat":"E", "network":"M.05", "new-workspace":"C.05",
        "notifications":"O.01", "onboarding":"B", "orca-profiles":"O.06",
        "orchestration-crew":"N.orchestration", "pet":"O.04", "plain-ssh-terminal":"F.05",
        "plugins":"L.05", "ports":"G.05", "provider-accounts":"N.accounts", "pull-request-page":"J.02",
        "repo":"C", "right-sidebar":"G", "runtime-access":"M.05", "settings":"N", "setup-guide":"B.05",
        "shared":"P", "sidebar":"C", "skills":"L.03", "source-control":"G.03",
        "sparse":"C.05.02", "ssh-authentication":"C.03", "standalone-terminal":"D.06",
        "star-nag":"O.01", "stats":"N.stats", "status-bar":"A.03", "tab-bar":"D.01", "tab-group":"D.02",
        "task-page":"J", "terminal":"F", "terminal-pane":"F", "terminal-quick-commands":"F.03",
        "ui":"P", "unexpected-signout":"O.01", "workspace-cleanup":"C.06",
        "workspace-emoji":"C.04.01", "workspace-space":"M.02", "worktree-creation":"C.05.01",
        "worktree-jump":"C.09", "wsl-drive-project":"M.04", "wsl-host-mark":"M.04",
        "wsl-host-stopped":"M.04", "wsl-move":"M.04"
    }
    for directory, row_id in domains_for_directory.items():
        if row_id not in rows:
            raise SystemExit(f"{directory}: missing directory queue {row_id}")
    buckets = {
        "src/renderer/src/main.tsx":"A",
        "src/renderer/src/popout.tsx":"M.03",
        "src/renderer/src/space.tsx":"M.02",
    }
    def file_mapping(p):
        exact = anchors.get(p, [])
        prefix = [r for d, ids in anchors.items() if p.startswith(d.rstrip("/")+"/") for r in ids]
        if exact:
            return ";".join(exact), "explicit"
        if prefix:
            return ";".join(sorted(set(prefix))), "family path"
        if p in module_routes:
            return module_routes[p]
        if p in buckets:
            return buckets[p], "entrypoint queue"
        if p.startswith(components):
            directory, sep, name = p.removeprefix(components).partition("/")
            if sep and directory in domains_for_directory:
                return domains_for_directory[directory], "directory queue; leaf review open"
        return "", "unassigned discovery candidate"
    rows_csv(INDEX / "module-coverage.csv",
             ("path", "static entrypoints", "coverage ids", "mapping", "JSX controls", "state predicates", "motion classes"),
             ([r["path"], ";".join(r["entrypoints"]), *file_mapping(r["path"]),
               len(r["uses"]), len(r["conditions"]), len(r["motion"])] for r in candidates))
    primitive_uses = [json.loads(line) for line in read(INDEX/"primitive-usage.jsonl").splitlines() if line]
    rows_csv(INDEX / "primitive-usage.csv",
             ("path", "line", "element", "primitive", "shared rule", "surface mapping", "mapping confidence", "handlers"),
             ([r["path"], r["line"], r["tag"], r["primitive"],
               primitives.get(Path(r["primitive"]).stem, "P"), *file_mapping(r["path"]), ";".join(r["events"])]
              for r in primitive_uses))
    rows_csv(INDEX / "native-host-coverage.csv",
             ("path", "line", "call", "coverage ids", "reviewed role"),
             ([r["path"], r["line"], r["text"], *native_routes[r["path"]]] for r in native_candidates))
    report = dict(source=head, reference_source=REFERENCE_HEAD, installed_tree=INSTALLED_TREE, domains=len(domains), rows=len(rows),
                  dispositions=dict(Counter(r["decision"] for r in rows.values())),
                  evidence=dict(evidence_counts), target_acceptance=dict(Counter(r["acceptance"] for r in rows.values())),
                  specification=dict(Counter(r["spec"] for r in rows.values())),
                  implementation=dict(Counter(r["implementation"] for r in rows.values())),
                  baseline_assurance=dict(Counter(r["baseline_result"] for r in rows.values())),
                  settings_targets=len(re.findall(r"'([^']+)'", settings.group(1))), top_level_views=len(views),
                  root_boundaries=len({e["id"] for k in ("modal","notice") for e in summary["registry"][k]}),
                  primitive_wrappers=len(primitives), primitive_use_sites=len(primitive_uses),
                  native_host_candidates=len(native_candidates), native_host_routes=len(native_routes),
                  source_discovery_candidates=len(candidates),
                  module_mapping=dict(Counter(file_mapping(r["path"])[1] for r in candidates)),
                  note="Structural validation only. No claim of exhaustive discovery, complete review or UI acceptance.")
    dump(PACKAGE / "coverage-audit.json", json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=True))

if __name__ == "__main__":
    main()
