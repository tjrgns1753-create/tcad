"""원격 출처·원본 해시·전체 배열과 해석 판정을 독립 재검사. 엔진 없음."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SHA = 'ddf01be947cad338f2905226733f5c49ee5d34b6'
RUN = '37974877904'


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from judge import CASES, evaluate


def main(root):
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha'] == summary['source']['git_head'] == SHA
    assert summary['source']['run_id'] == RUN and summary['runner']['runner_environment'] == 'github-hosted'
    assert summary['status'] == 'PASS' and summary['exit_code'] == 0 and not summary['omitted_outputs']
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    for record in summary['inputs']:
        blob = subprocess.check_output(['git', 'show', SHA + ':' + record['path']], cwd=repo, env=env)
        lf = blob.replace(b'\r\n', b'\n')
        assert any(len(b) == record['bytes'] and hashlib.sha256(b).hexdigest() == record['sha256']
                   for b in (blob, lf, lf.replace(b'\n', b'\r\n'))), record['path']
    for record in summary['outputs'] + [summary['log']]:
        path = root / ('outputs/' + record['path'] if 'path' in record else record['file'])
        blob = path.read_bytes()
        assert len(blob) == record['bytes'] and hashlib.sha256(blob).hexdigest() == record['sha256']
    out = root / 'outputs/e6nt_out'
    tests = json.loads((out / 'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps']) == {'matrix', 'judge', 'bias', 'caption', 'contacts'}
    assert all(r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
               for r in tests['steps'].values())
    records = json.loads((out / 'records.json').read_text(encoding='utf-8'))
    verdict = json.loads((out / 'verdict.json').read_text(encoding='utf-8'))
    assert evaluate(records) == verdict and verdict['pass'] is True and len(verdict['checks']) == 33
    assert sum(r['solves'] for r in records.values()) == 24
    for name, axis, side, voltage in CASES:
        record = records[name]
        blob = (out / (name + '_fields.json')).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == record['file_sha256']
        payload = json.loads(blob)
        assert payload['snapshot'] == record['snapshot']
        assert payload['source_evidence'] == record['source_evidence']
        point = record['measurement']['points'][0]
        for key in ('voltages', 'currents', 'converged'):
            assert payload['measurement'][key] == point[key]
        assert payload['measurement']['metadata'] == record['measurement']['metadata']
        # 판정기 재사용과 별도로 부호·0V·접점 교환 결과를 직접 점검한다.
        current = verdict['metrics'][name]['source_current_A_per_cm']
        assert current == 0. if voltage == 0. else math.copysign(1., current) == math.copysign(1., voltage)
        assert len(record['snapshot']['xy_um']) == 73 and record['device_cleanup'] is True
    for axis in ('x', 'y'):
        assert verdict['metrics'][axis + '_max_pos']['source_current_A_per_cm'] == -verdict['metrics'][axis + '_max_neg']['source_current_A_per_cm']
        assert verdict['metrics'][axis + '_max_pos']['source_current_A_per_cm'] == verdict['metrics'][axis + '_min_pos']['source_current_A_per_cm']
    prior = (repo / 'docs/audits/2026-10-07-e6np-readout-invalidation/raw/outputs/e6no_out/실제노드.json').read_bytes()
    assert (out / 'x_max_pos_fields.json').read_bytes() == prior
    print(json.dumps({'pass': True, 'inputs': len(summary['inputs']), 'raw_files': len(summary['outputs']) + 1,
        'actual_cases': 8, 'actual_solves': 24, 'checks': 33, 'axis_ratio': verdict['axis_current_ratio'],
        'entire_prior_export_unchanged': True, 'engine_imports': 0}))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
