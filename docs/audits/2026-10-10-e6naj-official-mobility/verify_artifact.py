"""엔진 없는 원본·실행·설치 helper 기록 대조."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from judge import judge, EXPECTED
ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'd726b8c48bf6064521af09c204807818d716331f'
RUN = '38057859918'
PLAN_SHA = '43b43558a4949363af10b9b2801454a0ad1d061378a13d6715a2b63ed3534516'


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
out = raw/'outputs/e6naj_out'
records = json.loads((out/'records.json').read_text(encoding='utf-8'))
assert set(records) == set(EXPECTED)
for label, r in records.items():
    assert r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
    assert sha((out/(label+'.log')).read_bytes()) == r['log_sha256']
rows = {label: json.loads((out/(label+'.json')).read_text(encoding='utf-8')) for label in EXPECTED}
verdict = judge(rows, PLAN_SHA)
assert json.loads((out/'verdict.json').read_text(encoding='utf-8')) == {
    'evidence_complete': True, 'model_evaluation': verdict, 'production_changed': False, 'material_calibration': 'NOT_VALIDATED'}
changed = subprocess.check_output(['git', 'diff', '--name-only', '7f98cd5', SOURCE, '--', 'tcad', 'tests', 'tcad_2d_stagewise.py'], cwd=ROOT)
assert changed == b''
print(json.dumps({'pass': True, 'model_evaluation': verdict, 'outputs_verified': len(s['outputs']),
    'solve_attempts': 0, 'production_changes': 0, 'seconds': s['duration_s']}, indent=2))
