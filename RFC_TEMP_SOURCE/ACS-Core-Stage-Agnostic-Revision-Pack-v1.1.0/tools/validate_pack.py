#!/usr/bin/env python3
"""Validate internal revision scope and embedded old reference. No product/runtime tests."""
import json, zipfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))

def assert_unique(values,label):
    assert len(values)==len(set(values)),f'duplicate {label}'

def validate():
    scope=read('contracts/scope.json')
    assert scope['revision_package_version']=='1.1.0'
    original=ROOT/'reference/ACS-Core-Cross-Harness-DevPack-v1.0.0.zip'
    with zipfile.ZipFile(original) as z:
        names=z.namelist()
        def legacy(filename):
            matches=[x for x in names if x.endswith('/'+filename)]
            assert len(matches)==1,(filename,matches)
            return json.loads(z.read(matches[0]))
        old_req=legacy('contracts/requirements.json')['requirements']
        old_t=legacy('tests/scenarios.json')['scenarios']
        old_ui=legacy('contracts/ui-feature-matrix.json')['features']
    r=read('contracts/requirements-scope.json')['requirements']
    t=read('contracts/scenario-scope.json')['scenarios']
    ui=read('contracts/ui-scope.json')['features']
    ops=read('contracts/api-scope.json')['operations']
    changes=read('contracts/change-items.json')['items']
    exp=scope['validation_target']
    assert len(r)==len(old_req)==exp['requirements']
    assert len(t)==len(old_t)==exp['scenarios']
    assert len(ui)==len(old_ui)==exp['ui_features']
    assert len(ops)==exp['api_operations']
    assert_unique([x['id'] for x in r],'requirement ids')
    assert_unique([x['id'] for x in t],'scenario ids')
    assert_unique([x['id'] for x in ui],'ui ids')
    assert_unique([x['operation_id'] for x in ops],'API operation ids')
    assert_unique([x['id'] for x in changes],'change item ids')
    assert {x['id'] for x in r}=={x['id'] for x in old_req}
    assert {x['id'] for x in t}=={x['id'] for x in old_t}
    assert {x['id'] for x in ui}=={x['id'] for x in old_ui}
    allowed={'P0_required','P1_required','P2_optional'}
    assert all(x['tier'] in allowed for x in [*r,*t,*ui,*ops,*changes])
    by_t={x['id']:x for x in t};by_r={x['id']:x for x in r}
    for x in t:
        assert x['requirements'] and all(k in by_r for k in x['requirements'])
    ids={x['id'] for x in changes}
    for x in changes:
        assert all(d in ids for d in x['depends_on'])
        assert all(k in by_r for k in x['old_requirements'])
        for tid in x['test_ids']:
            assert tid in by_t,(x['id'],tid)
            if x['tier'] != 'P2_optional':
                assert by_t[tid]['tier'] != 'P2_optional',(x['id'],tid,'P2 test cannot gate P0/P1')
    for x in changes:
        seen=set()
        def walk(cid):
            if cid in seen:raise AssertionError(f'dependency cycle {cid}')
            seen.add(cid)
            for dep in next(q for q in changes if q['id']==cid)['depends_on']:walk(dep)
            seen.remove(cid)
        walk(x['id'])
    import yaml
    api=yaml.safe_load((ROOT/'contracts/openapi-p1.yaml').read_text())
    emitted=[o['operationId'] for path in api['paths'].values() for k,o in path.items() if k in ('get','put','post','patch','delete')]
    p1={x['operation_id'] for x in ops if x['tier']=='P1_required'}
    assert set(emitted)==p1,(set(emitted)-p1,p1-set(emitted))
    assert len(emitted)==len(set(emitted))
    for x in ops:
        assert x['tier'] != 'P2_optional' or x['operation_id'] not in emitted
    m=api['components']['schemas']
    for obj,exts in [('Conversation',['unread_count','archived','muted']),('Message',['attachment_refs']),('Notice',['seen'])]:
        assert not (set(exts)&set(m[obj].get('required',[]))),(obj,m[obj].get('required'))
    refs=set()
    def follow(v):
        if isinstance(v,dict):
            if '$ref' in v and v['$ref'].startswith('#/components/schemas/'):refs.add(v['$ref'].split('/')[-1])
            for x in v.values():follow(x)
        elif isinstance(v,list):
            for x in v:follow(x)
    follow(api)
    assert refs <= set(m),(refs-set(m))
    state=read('handoff/ADOPTION_STATE_TEMPLATE.json')
    assert {x['id'] for x in state['items']}==ids
    assert all(x['status']=='unassessed' and not x['evidence_refs'] for x in state['items'])
    assert all(x['tier'] == 'P1_required' for x in ui if x['authority']=='host')
    print(json.dumps({'pass':True,'requirements':dict(Counter(x['tier'] for x in r)),'scenarios':dict(Counter(x['tier'] for x in t)),'ui':dict(Counter(x['tier'] for x in ui)),'operations':dict(Counter(x['tier'] for x in ops)),'change_items':dict(Counter(x['tier'] for x in changes)),'note':'Package static only; no ACS implementation verified'},ensure_ascii=False,indent=2))

if __name__=='__main__':validate()
