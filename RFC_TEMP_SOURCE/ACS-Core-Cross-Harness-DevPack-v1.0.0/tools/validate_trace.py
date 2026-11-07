#!/usr/bin/env python3
"""Structural acceptance oracle for supplied trace records. Never attests authenticity.
Use real evidence separately. This checker is NOT a delivery engine or a fake ACS.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

class TraceViolation(ValueError):
    pass

def validate_trace(events: list[dict[str, Any]]) -> None:
    messages: dict[str, dict[str, Any]] = {}
    operations: dict[str, dict[str, Any]] = {}
    bindings: dict[str, int] = {}
    if not isinstance(events, list):
        raise TraceViolation("Trace must be an array")
    for index, e in enumerate(events):
        try:
            kind = e['type']
            if kind == 'binding':
                old = bindings.get(e['receiver'], -1)
                if e['epoch'] < old:
                    raise TraceViolation('Binding epoch regressed')
                bindings[e['receiver']] = e['epoch']
            elif kind == 'message_committed':
                if e['message'] in messages:
                    if messages[e['message']] != e:
                        raise TraceViolation('Immutable message changed')
                messages[e['message']] = e
            elif kind == 'intent':
                if e['message'] not in messages:
                    raise TraceViolation('Intent before authoritative message')
                if e['operation'] in operations:
                    old = operations[e['operation']]['intent']
                    if old != e:
                        raise TraceViolation('Operation identity reused with changed input')
                else:
                    operations[e['operation']] = {'intent': e, 'count': 0, 'state': 'pending'}
            elif kind == 'handoff':
                if e['operation'] not in operations:
                    raise TraceViolation('Native handoff lacks durable intent')
                operation = operations[e['operation']]
                intent = operation['intent']
                message = messages[intent['message']]
                if message['activation'] == 'message_only':
                    raise TraceViolation('message_only invoked native input')
                if e['epoch'] != bindings.get(intent['receiver']) or e['epoch'] != intent['epoch']:
                    raise TraceViolation('Stale receiver epoch')
                if operation['count']:
                    replay = (e.get('replay_safe') is True and
                              e.get('dedup_scope') == intent['dedup_scope'] and
                              bool(e.get('replay_evidence_ref')))
                    no_effect = operation['state'] == 'definitively_not_admitted'
                    if not replay and not no_effect:
                        raise TraceViolation('Repeated native effect without non-admission/replay evidence')
                operation['count'] += 1
                operation['state'] = 'submitting'
            elif kind == 'outcome':
                operation = operations[e['operation']]
                state = e['state']
                if state not in ['accepted', 'definitively_not_admitted', 'unknown']:
                    raise TraceViolation('Unknown outcome vocabulary')
                if state != 'unknown' and not e.get('evidence_ref'):
                    raise TraceViolation('Claimed native outcome without evidence reference')
                if operation['state'] == 'accepted' and state != 'accepted':
                    raise TraceViolation('Confirmed admission was overwritten')
                operation['state'] = state
            elif kind == 'reply':
                refs = e['reply_to']
                if not refs:
                    raise TraceViolation('Reply has no explicit relation')
                for reference in refs:
                    original = messages[reference]
                    if e['sender'] != original['to'] or e['to'] != original['sender']:
                        raise TraceViolation('Reply author/recipient is not original peer')
                messages[e['message']] = e
            elif kind == 'wait_timeout':
                if e.get('resend') or e.get('cancel_peer'):
                    raise TraceViolation('Wait timeout altered communication')
            else:
                raise TraceViolation(f'Unsupported trace event {kind}')
        except (KeyError, TypeError) as exc:
            raise TraceViolation(f'Bad record {index}: {exc}') from exc
        except TraceViolation as exc:
            raise TraceViolation(f'Record {index}: {exc}') from exc

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    try:
        validate_trace(json.loads(args.trace.read_text(encoding='utf-8')))
    except (OSError, json.JSONDecodeError, TraceViolation) as exc:
        print(json.dumps({'valid':False,'error':str(exc),'evidence_class':'structural_check_only'},ensure_ascii=False))
        return 1
    print(json.dumps({'valid':True,'evidence_class':'structural_check_only','authenticity_verified':False}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
