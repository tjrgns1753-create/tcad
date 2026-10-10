"""엔진 없는 원본·실행·설치 helper 기록 대조."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from judge import judge, EXPECTED
ROOT = Path(__file__).resolve().parents[3]
SOURCE = '02c9605679b244cf6cf51ed64607737ea109f441'
RUN = '38058384455'
PLAN_SHA = '092d7042ee87364d4e32a051a88cde090e73dc5d28f0ee20c2b060635eab586e'


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise RuntimeError('ENGINE_FORBIDDEN')


sys.addaudithook(forbid)
sha = lambda data: hashlib.sha256(data).hexdigest()
raw = Path(sys.argv[1])
s = json.loads((raw/'summary.json').read_text(encoding='utf-8'))
assert s['source']['github_sha'] == s['source']['git_head'] == SOURCE
assert s['source']['run_id'] == RUN and s['runner']['github_hosted_confirmed'] is True
assert s['status'] == 'PASS' and s['exit_code'] == 0 and s['omitted_outputs'] == [] and s['log_truncated'] is False
assert sha((raw/'run.log').read_bytes()) == s['log']['sha256']
for r in s['outputs']:
    b = (raw/'outputs'/r['path']).read_bytes()
    assert len(b) == r['bytes'] and sha(b) == r['sha256']
for r in s['inputs']:
    b = subprocess.check_output(['git', 'show', SOURCE+':'+r['path']], cwd=ROOT)
    lf = b.replace(b'\r\n', b'\n')
    assert r['sha256'] in {sha(b), sha(lf), sha(lf.replace(b'\n', b'\r\n'))}
out = raw/'outputs/e6nal_out'
records = json.loads((out/'records.json').read_text(encoding='utf-8'))
assert set(records) == set(EXPECTED)
for label, r in records.items():
    assert r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
    assert sha((out/(label+'.log')).read_bytes()) == r['log_sha256']
rows = {label: json.loads((out/(label+'.json')).read_text(encoding='utf-8')) for label in EXPECTED}
verdict = judge(rows, PLAN_SHA)
assert json.loads((out/'verdict.json').read_text(encoding='utf-8')) == {
    'evidence_complete': True, 'model_evaluation': verdict, 'candidate': 'AUDIT_ONLY_CONTINUOUS_EXTENSION', 'production_changed': False, 'material_calibration': 'NOT_VALIDATED'}
changed = subprocess.check_output(['git', 'diff', '--name-only', '3cf49bc', SOURCE, '--', 'tcad', 'tests', 'tcad_2d_stagewise.py'], cwd=ROOT)
assert changed == b''
import copy
blocked = []
for label in ('zero_changed', 'wrong_candidate', 'extra_replacement', 'positive_model_drift', 'source_changed', 'solve_attempt'):
    m = copy.deepcopy(rows)
    if label == 'zero_changed': m['INTRINSIC']['models']['Z_D']['values'] = [1.0001]*4
    elif label == 'wrong_candidate': m['PURE_N']['candidate'] = 'PRODUCTION_VALIDATED'
    elif label == 'extra_replacement': m['PURE_N']['replaced_models'].append('mu_bulk_e')
    elif label == 'positive_model_drift':
        m['BOTH_POSITIVE_CONTROL']['models']['mu_bulk_e']['values'] = [1000.]*5
        m['BOTH_POSITIVE_CONTROL']['models']['mu_bulk_e_Node']['values'] = [1000.]*4
    elif label == 'source_changed':
        for row in m.values(): row['helper_source_lf_sha256'] = '0'*64
    else: m['PURE_N']['solve_attempts'] = 1
    try: judge(m, PLAN_SHA)
    except (AssertionError, KeyError, ValueError): blocked.append(label)
    else: raise AssertionError('FALSE_GREEN: '+label)
print(json.dumps({'pass': True, 'model_evaluation': verdict, 'outputs_verified': len(s['outputs']),
    'solve_attempts': 0, 'production_changes': 0, 'mutants_blocked': blocked, 'seconds': s['duration_s']}, indent=2))
