"""실행 출처·raw 해시·전체 노드·접점 완전성을 독립 재검사. 엔진 없음."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SHA = '87bc92277eb7219276bbf8f5345749559e00110f'
RUN = '37973087515'


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)


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
    out = root / 'outputs/e6nr_out'
    tests = json.loads((out / 'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps']) == {
        'caption', 'pure_caption', 'pure_export', 'contacts', 'snapshot', 'hover', 'readout', 'gate_control'}
    assert all(r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
               for r in tests['steps'].values())
    contacts = json.loads((out / 'contacts.log').read_text(encoding='utf-8').strip())
    assert contacts['mode'] == 'after' and len(contacts['cases']) == 8
    assert set(contacts['cases'].values()) == {'BLOCKED'} and contacts['normal_controls'] == 3
    assert contacts['engine_imports'] == 0
    check = json.loads((out / 'caption.json').read_text(encoding='utf-8'))
    assert check['pass'] is True and check['solves'] == 3
    assert check['live_api_equal'] is True and check['device_cleanup'] is True and check['export_unchanged'] is True
    assert check['ground_applied_V'] == 0 and check['ground_raw_potential_V'] > .3
    fields = check['snapshot']
    expected = []
    for i in check['ground_indices']:
        doping = check['NetDoping'][i]
        equilibrium_n = 1e-10 + .5 * abs(doping + math.sqrt(doping ** 2 + 4 * check['n_i'] ** 2))
        expected.append(check['V_t'] * math.log(equilibrium_n / check['n_i']))
    assert expected == check['ground_expected']
    error = max(abs(fields['potential'][i] - value) for i, value in zip(check['ground_indices'], expected))
    assert error == check['ground_formula_error_V'] and error <= 1e-9
    assert set(check['rendered']) == {'potential', 'electron', 'hole'}
    for layer, record in check['rendered'].items():
        assert record['nodes'] == 73
        text = record['text']
        assert '영역 Si' in text and 'Si_xmin=+0 V' in text and 'Si_xmax=+0.001 V' in text
        assert 'No interpolation' in text and ('원시 Potential' in text) == (layer == 'potential')
    blob = (out / '실제노드.json').read_bytes()
    assert hashlib.sha256(blob).hexdigest() == check['file_sha256']
    payload = json.loads(blob)
    measurement = payload['measurement']
    assert set(measurement['voltages']) == set(measurement['currents']) and len(measurement['currents']) == 2
    assert measurement['voltages'][measurement['sweep_contact']] == .001 and measurement['converged'] is True
    assert all(math.isfinite(v) for a in (measurement['voltages'], measurement['currents']) for v in a.values())
    assert measurement['metadata']['current_unit'] == 'A/cm'
    assert measurement['metadata']['device_dimension'] == 2
    assert measurement['metadata']['current_normalization'] == 'per_out_of_plane_depth'
    prior = json.loads((repo / 'docs/audits/2026-10-07-e6np-readout-invalidation/raw/outputs/e6no_out/실제노드.json').read_text(encoding='utf-8'))
    assert payload == prior and payload['snapshot'] == fields  # 전체 값과 접점·출처 동일.
    control = json.loads((out / 'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert control['pass'] is True and all(r['pass'] is True for r in control['checks'])
    print(json.dumps({'pass': True, 'inputs': len(summary['inputs']), 'raw_files': len(summary['outputs']) + 1,
        'blocked_cases': 8, 'normal_controls': 3, 'entire_actual_export_unchanged': True, 'engine_imports': 0}))


if __name__ == '__main__':
    main(Path(sys.argv[1]))


