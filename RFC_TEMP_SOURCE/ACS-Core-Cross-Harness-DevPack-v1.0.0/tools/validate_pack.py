#!/usr/bin/env python3
"""Offline package consistency check. Does not run ACS, Orca or any Harness."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

def read_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding='utf-8'))

def check_pack() -> dict[str, Any]:
    try:
        import yaml
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise RuntimeError('Install requirements-validation.txt first') from exc
    issues: list[str] = []
    checks: list[str] = []
    for path in ROOT.rglob('*.json'):
        try: json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc: issues.append(f'{path.relative_to(ROOT)}: {exc}')
    checks.append('all_json_parse')
    model = read_json('contracts/models.schema.json')
    Draft202012Validator.check_schema(model)
    checks.append('json_schema_draft_2020_12')
    fixtures=read_json('fixtures/index.json')['fixtures']
    for fixture in fixtures:
        schema={'$defs':model['$defs'],'$ref':'#/$defs/'+fixture['definition']}
        validator=Draft202012Validator(schema,format_checker=FormatChecker())
        errors=list(validator.iter_errors(read_json(fixture['path'])))
        if (not errors) != fixture['expected_valid']:
            issues.append(f"Unexpected fixture result: {fixture['path']}: {[e.message for e in errors]}")
    checks.append('positive_negative_schema_fixtures')
    api=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text(encoding='utf-8'))
    op_ids=[]
    def visit(x: Any) -> None:
        if isinstance(x,dict):
            if '$ref' in x:
                ptr=x['$ref']
                if not ptr.startswith('#/'):
                    issues.append('Unexpected external OpenAPI ref '+ptr)
                else:
                    node=api
                    try:
                        for segment in ptr[2:].split('/'):node=node[segment.replace('~1','/').replace('~0','~')]
                    except (KeyError,TypeError):issues.append('Unresolved OpenAPI ref '+ptr)
            for value in x.values():visit(value)
        elif isinstance(x,list):
            for value in x:visit(value)
    visit(api)
    for path,methods in api['paths'].items():
        expected=set(re.findall(r'\{([^}]+)\}',path))
        for method,operation in methods.items():
            if method not in ['get','put','post','delete','patch']:continue
            op_ids.append(operation['operationId'])
            declared={p['name'] for p in operation.get('parameters',[]) if p['in']=='path'}
            if declared!=expected:issues.append('Path parameter mismatch '+path)
            if not operation.get('responses'):issues.append('Missing responses '+path)
    if len(op_ids)!=len(set(op_ids)):issues.append('Duplicate operationId')
    checks.append('openapi_paths_and_internal_refs')
    # Check embedded model schemas match the canonical definitions.
    def transform(x):
        if isinstance(x,dict):return {k:(v.replace('#/$defs/','#/components/schemas/') if k=='$ref' else transform(v)) for k,v in x.items()}
        if isinstance(x,list):return [transform(v) for v in x]
        return x
    if api['components']['schemas']!=transform(model['$defs']):issues.append('OpenAPI schema drift')
    checks.append('canonical_schema_parity')
    req=read_json('contracts/requirements.json')['requirements']
    scenarios=read_json('tests/scenarios.json')['scenarios']
    tests={t['id']:t for t in scenarios}
    if len(tests)!=len(scenarios):issues.append('Duplicate test ID')
    if {r['id'] for r in req}!={f'R-{i:03d}' for i in range(1,41)}:issues.append('Missing requirement ID')
    wps=read_json('contracts/work-packages.json')['packages']
    ws={w['id']:w for w in wps}
    visiting=set();done=set()
    def walk(wid):
        if wid in visiting:raise ValueError('Work-package dependency cycle')
        if wid in done:return
        if wid not in ws:raise ValueError('Unknown dependency '+wid)
        visiting.add(wid)
        for dependency in ws[wid]['depends_on']:walk(dependency)
        visiting.remove(wid);done.add(wid)
    for wid in ws:walk(wid)
    for r in req:
        if r['work_package'] not in ws:issues.append('Unknown WP '+r['id'])
        if len(r['test_ids'])<2:issues.append('Insufficient test coverage '+r['id'])
        for tid in r['test_ids']:
            if tid not in tests or r['id'] not in tests[tid]['requirements']:issues.append('Traceability mismatch '+tid)
    checks.append('requirements_test_workpackage_traceability')
    sources=read_json('sources/source-lock.json')
    source_ids={s['id'] for s in sources['sources']}
    for name in ['acs_commit','orca_commit']:
        if not re.fullmatch('[0-9a-f]{40}',sources[name]):issues.append('Unpinned source '+name)
    ui=read_json('contracts/ui-feature-matrix.json')['features']
    for feature in ui:
        if feature['source_id'] not in source_ids:issues.append('Unknown UI source '+feature['id'])
        for test in feature['test_ids']:
            if test not in tests:issues.append('Unknown UI test '+test)
        for query in feature['queries']:
            if query not in op_ids and not query.startswith(('NativeViewProvider.','NativeWorkspaceProvider.')):issues.append('Unmapped UI query '+query)
        if not feature['degradation']:issues.append('Missing UI degradation '+feature['id'])
    checks.append('ui_coverage_and_source_lock')
    kinds={e['name'] for e in read_json('contracts/events-registry.json')['kinds']}
    if kinds != set(model['$defs']['Event']['properties']['kind']['enum']):issues.append('Event registry/schema drift')
    trans=read_json('contracts/delivery-transitions.json')
    states=set(trans['states'])
    for edge in trans['edges']:
        if edge['from'] not in states or edge['to'] not in states or not edge['requires']:issues.append('Invalid transition')
        if edge['from']=='unknown' and edge['to'] in ['queued','submitting']:issues.append('Unsafe unknown retry shortcut')
    checks.append('delivery_safety_graph')
    errors=read_json('contracts/error-codes.json')['codes']
    if len({e['code'] for e in errors})!=len(errors):issues.append('Duplicate error code')
    # Compile source without executing an implementation.
    compile((ROOT/'contracts/adapter_protocol.py').read_text(encoding='utf-8'),'adapter_protocol.py','exec')
    checks.append('adapter_protocol_python_compile')
    for name in ['README.md','START_HERE_CODEX.md','AGENTS.md','docs/00_SCOPE_AND_DOD.md','docs/10_ORCA_UI_READINESS.md','handoff/FINAL_REPORT_TEMPLATE.md']:
        if not (ROOT/name).is_file():issues.append('Missing entry '+name)
    checks.append('handoff_entries_present')
    return {'package_version':'1.0.0','evidence_class':'package_validation','passed':not issues,'checks':checks,'issues':issues,'counts':{'requirements':len(req),'scenarios':len(scenarios),'work_packages':len(wps),'ui_features':len(ui),'schemas':len(model['$defs']),'api_operations':len(op_ids),'schema_fixtures':len(fixtures)},'limitations':['No ACS implementation tests executed','No native Harness or Orca host executed','OpenAPI structural/ref/parity check, not a full external OpenAPI conformance validator']}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);args=p.parse_args()
    try:result=check_pack()
    except Exception as exc:
        print(json.dumps({'passed':False,'error':str(exc)},ensure_ascii=False));return 1
    text=json.dumps(result,ensure_ascii=False,indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(text+'\n',encoding='utf-8')
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
