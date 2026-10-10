"""실제 미분 증거를 기존 원본 입력 및 공개 helper 해시와 대조한다."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from judge import judge
ROOT = Path(__file__).resolve().parents[3]
SOURCE = '81e0844df10c7c5ab765ad4ceaa983641a949c74'
RUN = '38058776477'
PLAN_SHA = '461e774f1022a9b29b542ed579af34aad60603b1a4df1a33fad3669942b322e9'


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise RuntimeError('ENGINE_FORBIDDEN')


sys.addaudithook(forbid)
sha = lambda b: hashlib.sha256(b).hexdigest()


def bound_judge(record):
    counts = judge(record, PLAN_SHA)
    for row in record['rows']:
        case = row['case']
        p = ROOT/'docs/audits/2026-10-10-e6nal-mobility-zero-limit/raw/remote-run-89/outputs/e6nal_out'/(case+'.json')
        baseline = json.loads(p.read_text(encoding='utf-8'))
        assert record['helper_source_lf_sha256'] == baseline['helper_source_lf_sha256']
        assert row['carrier_value'] == baseline['inputs'][row['carrier']][row['node']]
        assert row['base_mobility'] == baseline['models'][row['model']]['values'][row['node']]
    return counts


def main():
    raw = Path(sys.argv[1])
    summary = json.loads((raw/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha'] == summary['source']['git_head'] == SOURCE
    assert summary['source']['run_id'] == RUN and summary['runner']['github_hosted_confirmed'] is True
    assert summary['status'] == 'PASS' and summary['exit_code'] == 0
    assert summary['omitted_outputs'] == [] and summary['log_truncated'] is False
    assert sha((raw/'run.log').read_bytes()) == summary['log']['sha256']
    for r in summary['outputs']:
        b = (raw/'outputs'/r['path']).read_bytes()
        assert sha(b) == r['sha256'] and len(b) == r['bytes']
    for r in summary['inputs']:
        b = subprocess.check_output(['git', 'show', SOURCE+':'+r['path']], cwd=ROOT)
        lf = b.replace(b'\r\n', b'\n')
        assert r['sha256'] in {sha(b), sha(lf), sha(lf.replace(b'\n', b'\r\n'))}
    out = raw/'outputs/e6nam_out'
    record = json.loads((out/'metrics.json').read_text(encoding='utf-8'))
    counts = bound_judge(record)
    assert json.loads((out/'verdict.json').read_text(encoding='utf-8')) == {
        'evidence_complete': True, 'counts': counts, 'scope': 'AUDIT_ONLY_NO_DD_OR_CALIBRATION',
        'mismatch_found': counts.get('NUMERICAL_DERIVATIVE_MISMATCH', 0) > 0}
    mutants = []
    for label in ('missing_row', 'duplicate', 'false_consistent', 'changed_source', 'changed_carrier', 'solve'):
        m = copy.deepcopy(record)
        if label == 'missing_row': m['rows'].pop()
        elif label == 'duplicate': m['rows'][1] = copy.deepcopy(m['rows'][0])
        elif label == 'false_consistent': m['rows'][0]['comparison']['status'] = 'FABRICATED_PASS'
        elif label == 'changed_source': m['helper_source_lf_sha256'] = '0'*64
        elif label == 'changed_carrier': m['rows'][0]['carrier_value'] *= 2.
        else: m['solve_attempts'] = 1
        try: bound_judge(m)
        except (AssertionError, KeyError, ValueError): mutants.append(label)
        else: raise AssertionError('FALSE_GREEN: '+label)
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'be5da0b', SOURCE, '--', 'tcad', 'tests', 'tcad_2d_stagewise.py'], cwd=ROOT)
    assert changed == b''
    print(json.dumps({'evidence_verified': True, 'counts': counts, 'mutants_blocked': mutants,
        'outputs_verified': len(summary['outputs']), 'solve_attempts': 0, 'production_changes': 0,
        'seconds': summary['duration_s']}, indent=2))


if __name__ == '__main__': main()
