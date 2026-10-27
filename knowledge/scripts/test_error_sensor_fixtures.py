#!/usr/bin/env python3
"""Fixture test for error-sensor.py is_error_payload — born from the
phantom-fires finding (2026-10-27): clean outputs mentioning error vocabulary
were raised as CANON ERROR banners. Run: python3 test_error_sensor_fixtures.py
Exit 0 = all fixtures pass."""
import importlib.util
import json
import os
import sys

HOOK = os.path.expanduser('~/.claude/hooks/error-sensor.py')
spec = importlib.util.spec_from_file_location('error_sensor', HOOK)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# (name, hook_input, expected_is_error)
CLEAN = [
    ('triage verdict stdout with rejected/failed words', {
        'tool_name': 'Bash',
        'tool_response': {'stdout': "logged: foo -> rejected — Josh: done\nclosed: filed (BSYS-30018)\nnewest failed job j-Ac88 was upstream\n", 'stderr': '', 'exit_code': 0},
    }, None),
    ('evidence check clean stdout mentioning not found', {
        'tool_name': 'Bash',
        'tool_response': {'stdout': 'PASS: file exists\n0 actionable of 46 pairs; nothing failed\n', 'stderr': '', 'exit_code': 0},
    }, None),
    ('read tool with error-vocabulary prose', {
        'tool_name': 'Read',
        'tool_response': {'type': 'text', 'file': {'filePath': '/tmp/x.md', 'content': 'the watchdog showed run-date vs filename mismatch and auth failures upstream\n'}},
    }, None),
    ('success dict with no exit code but no markers', {
        'tool_name': 'Bash',
        'tool_response': {'stdout': 'all good\n', 'stderr': ''},
    }, None),
]
ERRORS = [
    ('bash traceback exit 1', {
        'tool_name': 'Bash',
        'tool_response': {'stdout': '', 'stderr': 'Traceback (most recent call last):\n  File "x.py"\n', 'exit_code': 1},
    }, 'Traceback'),
    ('mcp explicit error', {
        'tool_name': 'mcp__x__y',
        'tool_response': {'is_error': True, 'text': 'HTTP 404\n{"message": "Not found"}'},
    }, 'HTTP 404'),
    ('bash stderr only', {
        'tool_name': 'Bash',
        'tool_response': {'stdout': '', 'stderr': 'zsh: permission denied\n', 'exit_code': 126},
    }, 'permission denied'),
    ('string response with strong marker', {
        'tool_name': 'mcp__x__z',
        'tool_response': 'unauthorized: token expired',
    }, 'unauthorized'),
    ('weak marker leading a string response', {
        'tool_name': 'mcp__x__w',
        'tool_response': 'failed: connection refused',
    }, 'failed'),
    ('weak marker later in prose string stays clean', {
        'tool_name': 'mcp__x__v',
        'tool_response': 'the ledger shows 183 errors in 14d and the probe failed yesterday; ' + 'x' * 200,
    }, None),
]

fails = 0
for name, data, expect in CLEAN + ERRORS:
    got = mod.is_error_payload(data)
    ok = (got is None) if expect is None else (expect in (got or ''))
    if not ok:
        fails += 1
        print(f'FAIL {name}: expected {"clean" if expect is None else expect}, got {str(got)[:80]!r}')
    else:
        print(f'pass {name}')

# regression guard: exit_code 0 short-circuit must fire BEFORE markers
d = {'tool_name': 'Bash', 'tool_response': {'stdout': 'rejected failed invalid not found\n', 'stderr': '', 'exit_code': 0}}
if mod.is_error_payload(d) is not None:
    fails += 1
    print('FAIL exit_code-0 short-circuit did not hold')
else:
    print('pass exit_code-0 short-circuit')

print('ALL PASS' if fails == 0 else f'{fails} FAILURES')
sys.exit(1 if fails else 0)
