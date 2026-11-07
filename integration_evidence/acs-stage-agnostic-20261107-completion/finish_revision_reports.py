"""Publish local development evidence after all scoped acceptance checks pass."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
PRIOR = ROOT / "integration_evidence/acs-stage-agnostic-20261106"
PACK = ROOT / "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def main():
    audit = read(OUT / "acceptance-audit.json")
    assert audit["implementation_complete_within_declared_scope"]
    now = datetime.now(UTC).isoformat()
    history = OUT / "prior-assessments"
    history.mkdir(exist_ok=True)
    names = ["adoption-state.json", "p0-assessment.json", "p1-api-assessment.json", "verification-results.json",
             "IMPLEMENTATION_REPORT.md", "CURRENT_TASK_STATE.md", "SCOPE-DELTA-REPORT.md"]
    for name in names:
        target = history / name
        if not target.exists():
            shutil.copyfile(PRIOR / name, target)
    previous = read(history / "adoption-state.json")
    old_items = {x["id"]: x for x in previous["items"]}
    changes = read(PACK / "contracts/change-items.json")["items"]
    scenarios = {x["id"]: x for x in audit["scenarios"]}
    items = []
    for item in changes:
        old = old_items[item["id"]]
        paths = set(old.get("observed_code_paths", []))
        paths.update(x["path"] for x in old.get("observed_code", []) if "path" in x)
        paths.update(re.findall(r"(?:runtime|runtime_deployment|sdk)/[\w/.-]+\.(?:py|ts|sql|json)", item.get("reuse_first", "")))
        paths = sorted(p for p in paths if (ROOT / p).is_file())
        items.append({**item, "status": "retained_verified", "assessed_at": now,
            "assessment_scope": "v1.1 current supported service/Native configurations; qualification-matrix.json retains unqualified combinations",
            "implementation_gaps_in_declared_scope": [],
            "scenario_evidence": [{"id": identifier, "status": scenarios[identifier]["status"],
                "detail": "integration_evidence/acs-stage-agnostic-20261107-completion/acceptance-audit.json"}
                for identifier in item["test_ids"]],
            "observed_code": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths],
            "prior_assessment": "integration_evidence/acs-stage-agnostic-20261107-completion/prior-assessments/adoption-state.json#" + item["id"],
            "qualification_limit": "qualification-matrix.json" if item["tier"] == "P0_required" or item["id"] in {"C16", "C17", "C18", "C21", "C24"} else None,
            "next_actions": []})
    patch = git("diff", "--binary", "--no-ext-diff")
    source = {"repository": str(ROOT), "branch": git("branch", "--show-current").decode().strip(),
              "head": git("rev-parse", "HEAD").decode().strip(), "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
              "tracked_binary_diff_sha256": hashlib.sha256(patch).hexdigest(), "digest_format": "raw git diff --binary --no-ext-diff bytes",
              "working_tree": "dirty_uncommitted", "committed": False, "pushed": False,
              "upstream": git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").decode().strip(),
              "receiver_sync_action": "none", "observed_at": now}
    write(OUT / "source-state.json", source)
    state = {"schema_version": "acs-adoption-state/1", "revision_package_version": "1.1.0", "observed_at": now,
        "source_version": "2.3.1 source/candidate wheel; installed production is a separate observation",
        "source_head": source["head"], "source_tree": source["tree"], "branch": source["branch"],
        "dirty_patch_digest": source["tracked_binary_diff_sha256"], "source_state": source,
        "development_status": "complete_in_declared_scope_with_explicit_qualification_limits",
        "request_scope": "P0 and P1 plus user-requested P2 extensions C22-C25",
        "prior_intent": "ACS-Core-Cross-Harness-DevPack-v1.0.0", "old_package_execution_stage": "not_assumed",
        "items": items, "milestones": audit["milestones"],
        "acceptance_audit": "integration_evidence/acs-stage-agnostic-20261107-completion/acceptance-audit.json",
        "qualification_matrix": "integration_evidence/acs-stage-agnostic-20261107-completion/qualification-matrix.json",
        "final_report": "integration_evidence/acs-stage-agnostic-20261107-completion/FINAL_REPORT.md",
        "prior_assessment_history": ["integration_evidence/acs-stage-agnostic-20261107-completion/prior-assessments/adoption-state.json"],
        "milestone_reason": "Current real-service/SDK/installation/fault acceptance and exact-byte Native evidence are bound per scenario. P0 is qualified only for the named combinations; actual Orca and untested Native combinations are not claimed.",
        "external_qualification_limits": audit["limits"], "active_runners": [], "pg_lease": "none",
        "production_changes": False, "new_model_calls_in_this_continuation": 0}
    write(PRIOR / "adoption-state.json", state)
    write(PRIOR / "p0-assessment.json", {"schema_version": "acs-p0-assessment/1", "observed_at": now,
        "overall": audit["milestones"]["CORE_P0_QUALIFIED"], "source_state": source,
        "items": [x for x in items if x["tier"] == "P0_required"],
        "scenario_details": state["acceptance_audit"], "qualification_matrix": state["qualification_matrix"],
        "prior_assessment": "integration_evidence/acs-stage-agnostic-20261107-completion/prior-assessments/p0-assessment.json"})
    write(OUT / "api-assessment.json", {"schema_version": "acs-api-completion/1", "observed_at": now,
        "source_state": source, "operations": audit["api_operations"], "P1_count": 22, "P2_count": 13})
    write(PRIOR / "p1-api-assessment.json", {"schema_version": "acs-p1-api-assessment/1", "observed_at": now,
        "operations": [x for x in audit["api_operations"] if x["tier"] == "P1_required"],
        "CLIENT_P1_CONTRACT_READY": True, "ORCA_HOST_QUALIFIED": False,
        "current_exit_audit": state["acceptance_audit"], "source_state": source,
        "prior_assessment": "integration_evidence/acs-stage-agnostic-20261107-completion/prior-assessments/p1-api-assessment.json"})
    requirements = read(PACK / "contracts/requirements-scope.json")["requirements"]
    for row in requirements:
        row["change_items"] = [x["id"] for x in items if row["id"] in x["old_requirements"]]
        assert row["change_items"], row
        row["status"] = "verified_with_declared_scope_and_qualification_limits"
    write(OUT / "requirements-assessment.json", {"observed_at": now, "requirements": requirements,
        "qualification_matrix": "qualification-matrix.json", "scenario_audit": "acceptance-audit.json"})
    ui = read(PACK / "contracts/ui-scope.json")["features"]
    for row in ui:
        row["status"] = "verified_service_contract" if row["authority"] == "ACS" else "verified_delegation_and_typed_unavailable_contract"
        row["actual_UI_or_Orca_Host_qualification"] = False
        row["evidence"] = "acceptance-audit.json; sdk-verification.json"
        if row["tier"] == "P2_optional":
            row["activation"] = "explicit_current_user_request"
            row["evidence"] = "p0-p1-final.xml; p2-initial.xml (reviewed HTTP-only delta)"
    write(OUT / "ui-contract-assessment.json", {"observed_at": now, "features": ui})
    decisions = []
    for identifier, change, paths, reference, delta, impact in [
        ("D01", "C01,C04,C06", ["runtime/communication.py", "runtime/communication_dispatch.py", "runtime/delivery.py"],
         "mailbox-notification-coordinator.ts; structured-mailbox-pointer-delivery.ts", "复用现有 Message/operation/Outbox/NodeJournal 和维护器，按缺口验证，不引入任务编排权威", "消息、Native ACK 和显式 reply 保持分层；活动 wait 不重复 Native 唤醒"),
        ("D02", "C02-C08", ["runtime/native_handoff.py", "runtime/native_input_observations.py", "runtime/receiver_lifecycle_node.py"],
         "structured-agent-session-input-readiness.ts; terminal-authority/", "保留当前受信准入、签名生命周期和原操作回查；按真实版本限定支持", "unknown 不重投，busy/审批/draft 保持保护，旧代次不能产生新输入"),
        ("D03", "C16-C21", ["sdk/orca-receiver-port.ts", "sdk/integration-ports.ts", "runtime/signed_harness_adapter.py"],
         "docs/reference/plugin-host-api.md; structured-agent-session-input-handover.ts", "采用现有受权端口与委托合同；缺实际 Host 注册/原子入口时 typed host_extension_required", "Core/Host 授权独立且 Native 单输入 owner；Native transcript 不成为 ACS 消息权威"),
        ("D04", "C22-C25", ["runtime/communication_client_state.py", "runtime/communication_client_search.py", "runtime/communication_client_attachments.py"],
         None, "当前用户明确要求交付 P2，核验全部13操作、7场景和4个来源条目", "个人状态按 viewer 隔离；CAS、digest、实时 ACL 和附件生命周期保持"),
        ("D05", "C01,C12,C16", ["runtime/communication_http.py", "runtime_tests/test_communication_http_auth.py"],
         None, "仅在 include_native_source=true 时向 facade 转交新增关键字；新增默认/false/true 回归", "保持旧读取调用形状、原文与独立续读；没有权限或 schema 扩张"),
        ("D06", "C01,C05", ["runtime/communication.py", "runtime_tests/test_communication.py"],
         None, "T006 按 v1.1 P0-01 的旧 MCP 兼容优先级裁决，保留提交前歧义拒绝与显式选择", "零广播；不冒称原先先落 Inbox 的 GWT 已原样通过"),
        ("D07", "C10", ["runtime/communication_http.py"], None,
         "对历史 Native 记录使用逐文件差异与影响分析；HTTP-only 变更由当前组合重验", "不拼接为一轮新 Native 结果、不外推 Shared/物理双机/实际 Orca/cold recovery"),
    ]:
        decisions.append({"id": identifier, "change_item": change, "actual_ACS_paths": paths,
            "actual_Orca_paths_or_revision": {"revision": "53fbfded41b8b0462d7ccd029475f89d12aa9bf5", "paths": reference,
                "provenance": "existing pinned inspection/documentation in sdk/ORCA-RECEIVER-INTEGRATION.md; not a new claim about current upstream"} if reference else None,
            "already_implemented": True, "gap": "缺精确运行证据；D05另有已复现的旧调用形状兼容缺陷" if identifier == "D05" else "按当前源码和场景核验，未另建同义模块",
            "reuse_first_option": "现有 Domain、Driver/Receiver、SDK 和存储边界", "chosen_delta": delta,
            "why_minimal": "保留已满足合同的实现，仅修改被失败直接证明的HTTP调用及补齐验收",
            "security_impact": impact, "tests": "acceptance-audit.json 的对应场景/真实服务/SDK证据",
            "evidence_refs": ["acceptance-audit.json", "source-impact-review.json", "qualification-matrix.json"], "migration_needed": False})
    write(OUT / "DECISION_LOG.json", {"observed_at": now, "decisions": decisions})
    verification = {"schema_version": "acs-v11-verification/2", "observed_at": now, "runs": audit["runs"],
        "sdk": {"passed": 210, "typescript_strict": "passed", "artifact": "sdk-verification.json"},
        "qualification": audit["milestones"], "source_state": source,
        "retained_native": "retained-native-evidence.json", "wheel": "package-facts.json",
        "reviewed_source_delta": "source-impact-review.json", "static_checks": "static-verification.json",
        "failure_history": ["core-components: optional YAML module missing at collection",
            "core-components-with-contract-tools: stopped after sustained sandbox nonprogress; same selected suite passes in core-components-final",
            "exact-completion-a: three test-fixture setup errors; all original assertions retained and pass in b",
            "p0-p1-current: 500 passed/1 failed/3 skipped; ordinary HTTP read forwarded the optional false keyword; fixed without weakening the original assertion and covered by three current compatibility cases plus the final complete rerun",
            "read-compatibility-fix: stopped sandbox ASGI nonprogress; all three same-source cases pass in read-compatibility-final",
            "native-fences-components: one nonexistent target path; zero tests executed; corrected in final"],
        "test_totals_are_separate_not_summed": True, "production_changes": False, "new_model_calls": 0}
    write(OUT / "verification-results.json", verification)
    write(PRIOR / "verification-results.json", verification)
    table = "\n".join(f"| {r['id']} | {r['counts']['passed']} | {r['counts']['failed'] + r['counts']['errors']} | {r['counts']['skipped']} | `{r['junit']}` |"
                      for r in audit["runs"])
    package = read(OUT / "package-facts.json")
    report = f"""# ACS Core v1.1.0 开发与验收结果

截至 2026-11-07，P1 通信服务与 P2 扩展完成本地验收。P0 为
`qualified_with_specific_blockers`：已验证的 Codex/OpenCode owner/native 组合成立，
其他平台、权限模式和实际 Orca Host 按下述矩阵单列。此结论不代表全平台原生资格。

## 0. 实际版本和交付源码

- 源码：`{source['repository']}`，分支 `{source['branch']}`。
- HEAD：`{source['head']}`；HEAD tree：`{source['tree']}`。
- 工作树含原有成果及本轮增量，尚未提交、Push、合并、发布或生产切换。
- 当前候选包元数据版本 2.3.1；wheel SHA-256：`{package['sha256']}`。
  186 个包内文件与当前源码、临时安装后的字节一致，见 `package-facts.json`。
- 跟踪改动的原始 binary diff 摘要、每轮命令、逐文件源码摘要与原始结果分别见
  `source-state.json` 和各测试 JSON/XML/log；HEAD 本身不代表这批未提交源码。

## 1. 范围、实现和实际增量

25 项 C、40 项 R、96 个原始场景、35 个 API 和 30 项客户端来源已逐项映射，
见 `acceptance-audit.json`、`requirements-assessment.json`、`api-assessment.json`、
`ui-contract-assessment.json`。开发包原件和此前失败记录均保留。

本次修复普通 HTTP 消息读取对旧 facade 的兼容问题：默认和显式 false 不传新增
`include_native_source` 参数，显式 true 才请求来源扩展；原文和独立续读保持原语义。
`source-impact-review.json` 验证反向差异能精确重建修复前捕获字节，差异见 `runtime-change.diff`。
三条路径均有直接回归。另在既有 Runtime/SDK 实现上补齐 9 项直接验收：双设备读水位和请求去重、
真实 OAuth/TCP 的 13 个 P2 操作、双连接草稿 CAS、四个真实写进程中断点、
安装后后台维护，以及附件 URL/私有 ID 的实际拒绝。初轮夹具问题和复测分开记录。
现有消息、operation、Outbox、Node/DriverJournal 和 Root/Route 身份继续作为原权威。

## 2. P0：受信通信与 Native 边界

C01–C11 在声明配置内的实现与安全回归已核验。可信 sender、显式 reply_to、
message_only、非消费 read、长 UTF-8 续读、断连后原 handle 恢复、签名生命周期、
最后准入、人工 blocker、旧代次隔离和未知副作用不重投均有对应证据。

- 保留的 E4（Native/Core-MCP 栈字节一致，HTTP 增量单列）：Windows Codex 0.166.0 → WSL OpenCode 1.18.34，
  普通 A/B、两条消息、一条显式关联回复、B 一次 Native 输入、A 的真实 wait satisfied。
  Native/签名接收器及 Project/MCP 收发/等待机制保持原字节。901 个捕获文件中的
  普通 HTTP facade 与对应测试有已审查增量，已由当前组合回归重验，见 `retained-native-evidence.json`。
- Codex 接收工厂的独立 B 输入/显式回复证据 b，以及两端签名生命周期 E3，按
  相同 Native 栈摘要保留。b 的旧 Core wait 不冒充最终 wait；后者由独立 e 和当前 PG 验证。
- 当前 wheel 的独立后台进程在发送客户端退出后推进已提交消息；这是隔离安装 E2，
  Native 使用明确的回调夹具，不代表生产服务升级或真实模型轮次。

原始场景并未被一律改写为 pass：T006 依据 v1.1 的旧 MCP 兼容优先级保留
提交前 `endpoint_binding_ambiguous` 拒绝，零广播，随后可显式选择接收端；它不等于
旧“先落 Inbox”的原样通过。T031 的安全原生 enqueue 前提未在当前支持集中成立，
按 typed unsupported/busy deferred 验证。其余场景也保留原 GWT 与实际证据范围。

`CORE_P0_QUALIFIED = qualified_with_specific_blockers`。

## 3. P1：可由客户端实际消费的通信服务

22 个 P1 操作由实际 Node SDK → OAuth/TCP/HTTP/SSE → PG 链路验证，
包括身份/项目/联系人、空会话到首条消息、发送/原文/显式回复、投递/原 operation、
receiver/恢复/notice、快照、断线重放和撤权。MCP 与 HTTP 使用同一 Domain/权限。

26 个 P1 场景与 30 项来源合同逐项核对；NativeLink/SourceLink 保留独立来源和
Host 授权，Native 输出不能成为 ACS reply。Orca 端口通过协议、单 owner、
授权和 typed unavailable 测试；本地没有实际接通可资格化的 Orca Host。

`CLIENT_P1_CONTRACT_READY = true`；`ORCA_HOST_QUALIFIED = false`。

## 4. P2：本次明确交付的扩展

| 变更项 | 当前行为与验证 |
|---|---|
| C22 | viewer 私有读水位/未读及 notice seen；跨设备可读，水位不回退，不改变 Native/reply |
| C23 | viewer 私有草稿、静音/归档偏好；双设备 CAS 一方 409，精确重试保存原结果 |
| C24 | 私有 reservation、完整上传、digest/MIME/大小校验、finalize、受权读取、消息 pin 与清理；断线重传复用原计划；URL 抓取字段与猜测私有 ID 被拒绝 |
| C25 | 受权消息全文的字面子串搜索、UTF-8 摘要、稳定游标与撤权；不泄漏其他参与者正文或数量 |

13 个 P2 API 都有真实服务调用证据。附件仍由明确配置启用；Native 二进制
附件注入继续 typed unsupported。个人状态和草稿不会扩大收发信或项目权限。
`P2_EXTENSIONS_READY = true`，限定已列服务行为。

## 5. 验证、失败和复现

| 批次 | 通过 | 失败/错误 | 跳过 | 原始证据 |
|---|---:|---:|---:|---|
{table}
| SDK/严格 TypeScript | 210 | 0 | 0 | `sdk-verification.json`、`sdk.log`、`typescript.log` |

各行是独立批次，存在重叠，不能相加为单次全量通过。每轮捕获字节在运行前后
不变；最终组合与当前一致，历史组件/存储批次的 HTTP-only 增量由最终组合覆盖，
逐文件差异记录在 audit 中。跳过项按真实模型 opt-in、缺额外运行环境或平台条件逐条保存在 XML/log；
当前已有独立 E3/E4 证据与它们分别记录。

E0 开发包 50 文件及 manifest 校验、scope 一致性、客户端/SDK/P1 OpenAPI
导出检查、Ruff 与严格 TypeScript 通过。当前 wheel 离线构建并临时安装，未改变既有安装。
常用复现入口为 `tools/runtime/cross_harness_verify.py`，仅使用命名的
`acs-communication-test-20261031 / acs_communication_test`；精确命令见每轮 JSON。
本轮没有调用外部模型服务，也没有重放历史 Native 验收计划；本地通信 API 均已实际调用验证。

首轮组合为 500 通过、1 失败、3 跳过，暴露并修复了上述旧读取调用形状兼容问题；
原断言完整保留，最终组合对修复后的当前源码重新验收。首次收集缺 YAML 工具、
沙箱内无进展后中断、三项新增夹具错误及目标路径错误
都保留在各自旧结果中；最终通过结果不覆盖它们。早期证据的状态改写前另存于
`prior-assessments/`，当前 canonical 状态仍在原 `acs-stage-agnostic-20261106/adoption-state.json`。

## 6. 数据迁移与回滚

本次增量没有生产 schema 或用户数据变更。现有显式 additive adoption、
旧作者未知保留、DriverJournal adoption/失败回滚、旧消息/回复/请求键/未知输入保留
均由真实 PG/SQLite 用例核验。四个事务中断点在真实写进程被停止后，消息、回复、
operation、Outbox、dedup 和事件 intent 全部回滚；同原 key 恢复只得到一个逻辑结果。
安装验收验证只读启动检查，正常启动不隐式采用旧 schema。

## 7. 尚未取得的资格及具体前提

完整记录见 `qualification-matrix.json`。实际 Orca Host 需要其受信 verifier adapter
及串行原子输入扩展被注册并独立运行；远端原始 journal reader 也需明确的受权读端口。
物理双机和 Windows Shared/restricted Native 组合需要对应隔离环境与实际版本/权限验收。
当前原进程失效时的自动 cold recovery 没有受信的原 process/session/generation 证明，
继续 unknown/unsupported；单独空 Session CLI 探测不扩大生产恢复能力。

这些组合没有被冒认为已通过。WSL 清理仅证明自有进程组已空，
`subtree_containment=false`。新增 Claude/Pi 完整 Driver 没有本包 25 项所需的确切目标资格。
本地声明范围内的实现与验收已闭合；受控 Native/Host 夹具仅用于明确的协议测试，
实机范围按矩阵限定。

## 8. 交付状态

实际源码与证据保留在当前工程工作树，未提交、未 Push、未部署。没有其他 clone
的同步动作。扩大支持组合时应先具备第 7 节条件，再取得独立资格；当前本地交付
由本报告、机器状态与原始证据共同限定。
"""
    (OUT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    (PRIOR / "IMPLEMENTATION_REPORT.md").write_text(report, encoding="utf-8")
    delta = """# v1.1 范围和证据裁决

| 输入条款 | 本次采用行为 | 实际路径/证据 |
|---|---|---|
| v1.0 WP 线性状态 | 按 C01–C25 当前源码核验；历史状态存档 | adoption-state.json；prior-assessments/ |
| v1.1 默认 P2 可选 | 当前用户明确要求 P2；交付 C22–C25 的全部 13 操作，保留 canonical tier | api-assessment.json；exact-completion-b.xml；p2-initial.xml |
| 旧 T006 要先落 Inbox | v1.1 P0-01 旧 MCP 返回语义优先，保持歧义时提交前拒绝，零广播与显式选择 | test_configuration_selects_one_real_receiver_and_rejects_another_slots_receiver；acceptance-audit.json |
| T031 verified enqueue 前提 | 当前未声明安全原生 enqueue；busy deferred、queue/steer typed unsupported，不将 queued 当 consumed | Native 输入观察/签名 Adapter 回归；qualification-matrix.json |
| P1 等于真实 Orca 接通 | 22 通信服务 + Host 委托/降级合同通过；实际 Host 单独保持未资格化 | P1 headless、SDK210、ui-contract-assessment.json |
| 历史 Native 证据 | e 的 Native/Core-MCP 栈保持；普通 HTTP facade/测试增量经当前组合验证；b/g 的 Core wait 后续变化另列 | retained-native-evidence.json；qualification-matrix.json |
| 普通 read 兼容 | 只在 include_native_source=true 时转交扩展参数，保持默认/false 的旧调用形状；不削弱原续读断言 | runtime/communication_http.py；read-compatibility-final.*；p0-p1-final.* |
| 早期缺 lifecycle/rebind/wake 描述 | 当前实现和签名/TLS/PG 回归已存在，纠正旧台账；原描述归档 | 当前 C05–C07 与 C11；p0-p1-final.* |
| 运行包版本与生产版本 | 同为 2.3.1 的候选由 wheel SHA 和逐文件字节区分，仅临时安装 | package-facts.json；T090 |

没有改动开发包原件、历史失败日志或生产数据。完整原 GWT 保留，只有有证据的
适用行为与修订裁决才标为已核验；不声称 96 个旧 Given/When/Then 原样全通过。
"""
    (OUT / "SCOPE-DELTA-REPORT.md").write_text(delta, encoding="utf-8")
    (PRIOR / "SCOPE-DELTA-REPORT.md").write_text(delta, encoding="utf-8")
    current = """# 2026-11-07 当前工程交付

本次 P0/P1/P2 的声明范围内开发与可取得的验收已闭合；P0 为
qualified_with_specific_blockers，P1 与 P2 服务就绪，实际 Orca Host 未资格化。

权威入口：`../acs-stage-agnostic-20261107-completion/FINAL_REPORT.md`、
`adoption-state.json` 与 completion 的 `acceptance-audit.json`、`qualification-matrix.json`。
旧状态已存 `completion/prior-assessments/`；不能继续按其中的“未发现 OpenCode”、
“缺两 lifecycle module”或“P2 不扩展”描述当前任务。

当前没有测试 runner、PG lease 或待审批动作。本轮外部模型服务调用数为 0；
本地通信 API 的35个操作已实际验证。
旧 Native 计划不可重放；当前验收没有访问生产 Core、既有联系人或更改已有安装。

源码 D:/Chatgpt/Agent-collaboration，codex/core-cleanup，HEAD
19d7881d49ee887315c54c5bc02e0cc424061376；未提交/Push/发布，原有工作保持。
如后续扩大 Native/Host 支持范围，按矩阵列出的环境/可信端口条件另取资格，
不把已有 scoped pass 外推为实际 Orca、物理双机、Shared/restricted 或 cold recovery。
"""
    (PRIOR / "CURRENT_TASK_STATE.md").write_text(current, encoding="utf-8")
    (OUT / "WORK_STATE.md").write_text(current, encoding="utf-8")
    for script in ("build_revision_acceptance.py", "finish_revision_reports.py", "prepare_revision_artifact_facts.py",
                   "run_revision_completion.py", "run_revision_sdk.py", "verify_revision_static.py", "describe_revision_delta.py"):
        text = (ROOT / ".tmp" / script).read_text(encoding="utf-8")
        text = text.replace("ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())",
            "ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())")
        (OUT / script).write_text(text, encoding="utf-8")
    print(json.dumps({"items": len(items), "requirements": len(requirements), "scenarios": len(scenarios),
                      "API": len(audit["api_operations"]), "UI": len(ui), "milestones": audit["milestones"]}))


if __name__ == "__main__":
    main()
