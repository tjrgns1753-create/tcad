"""원격 산출물 해시 및 순수 배열 재판정. 로컬 엔진 import 금지."""
import hashlib
import json
import sys
from pathlib import Path


def deny_engine(event, args):
    if event == 'import' and args[0].split('.')[0] in ('devsim', 'viennaps', 'viennals'):
        raise AssertionError('LOCAL_ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny_engine)
import common as C
import matched_judge as J

RAW = C.HERE / 'raw'
summary = json.loads((RAW / 'summary.json').read_text())
assert summary['source']['github_sha'] == 'ef0140593a0190cb974ec5a2c79cc7abda7ed212'
assert summary['source']['git_head'] == summary['source']['github_sha']
assert summary['source']['run_id'] == '37429019975'
assert summary['runner']['github_hosted_confirmed'] is True
assert summary['packages']['devsim'] == '2.11.0'
assert summary['status'] == 'PASS' and summary['exit_code'] == 0
assert summary['log_truncated'] is False and summary['omitted_outputs'] == []
for entry in summary['outputs']:
    path = RAW / 'outputs' / entry['path']
    data = path.read_bytes()
    assert len(data) == entry['bytes']
    assert hashlib.sha256(data).hexdigest() == entry['sha256'], str(path)
log = (RAW / 'run.log').read_bytes()
assert len(log) == summary['log']['bytes']
assert hashlib.sha256(log).hexdigest() == summary['log']['sha256']
out = RAW / 'outputs/e6ne_out'
saved = json.loads((out / 'result.json').read_text())
recomputed = J.judge(out)
assert recomputed == saved, 'REJUDGEMENT_CHANGED'
assert saved['status'] == 'MATCHED_REFERENCE_PASS'
expected_checks = sum(2 + len(C.P.M.VOLTAGES[d]) + 2 * len(C.P.M.SNAP_BIASES[d])
                      for d in C.P.M.DIRECTIONS)
assert expected_checks == 28
assert len(saved['checks']) == expected_checks and all(c['pass'] is True for c in saved['checks'])
record = json.loads((out / 'reference/record.json').read_text())
assert sum(d['solve_attempts'] for d in record['devices'].values()) == 17
assert sum(d['solves'] for d in record['devices'].values()) == 17
assert all(d['solve_failures'] == d['snapshot_failures'] == 0 and d['cleanup_ok'] is True
           for d in record['devices'].values())
assert C.preflight() == C.PLAN_SHA
metrics = saved['metrics']
print(json.dumps({
    'artifact_hashes_checked': len(summary['outputs']) + 1,
    'rejudgement_equal': True,
    'checks': len(saved['checks']),
    'actual_1d_solves': 17,
    'new_2d_solves': 0,
    'max_current_relative': max(c['relative'] for d in metrics.values() for c in d['currents']),
    'max_carrier_relative': max(max(p['carriers_relative'].values()) for d in metrics.values() for p in d['profiles']),
    'max_potential_V': max(p['potential_max_V'] for d in metrics.values() for p in d['profiles']),
    'max_y_spread_V': max(p['y_spread_V'] for d in metrics.values() for p in d['profiles']),
    'max_field_relative': max(p['field_peak_normalized'] for d in metrics.values() for p in d['profiles']),
    'local_engine_imports': 0,
    'production_gate_released': False,
}, indent=2))
