"""실행 출처·raw 해시·전체 노드·접점 완전성을 독립 재검사. 엔진 없음."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SHA = '086911bdb66f99db1b787cacbf8b75055b195410'
RUN = '37973819504'


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
    out = root / 'outputs/e6ns_out'
    tests = json.loads((out / 'tests.json').read_text(encoding='utf-8'))
    assert tests['pass'] is True and set(tests['steps']) == {
        'gui_bias', 'pure_bias', 'validity', 'caption', 'contacts', 'export', 'hover', 'snapshot', 'readout'}
    assert all(r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
               for r in tests['steps'].values())
    contacts = json.loads((out / 'contacts.log').read_text(encoding='utf-8').strip())
    assert contacts['mode'] == 'after' and len(contacts['cases']) == 8
    assert set(contacts['cases'].values()) == {'BLOCKED'} and contacts['normal_controls'] == 3
    assert contacts['engine_imports'] == 0
    pure = json.loads((out / 'pure_bias.log').read_text(encoding='utf-8').strip())
    assert pure['mode'] == 'after' and len(pure['cases']) == 6 and set(pure['cases'].values()) == {'BLOCKED'}
    assert pure['normal_bias_controls'] == 3 and pure['engine_imports'] == 0
    check = json.loads((out / 'bias.json').read_text(encoding='utf-8'))
    assert check['pass'] is True and check['total_solves'] == 9
    assert check['fault_injection_after_actual_success'] is True and check['export_unchanged'] is True
    assert set(check['cases']) == {'normal', 'wrong_source_voltage', 'wrong_ground_voltage'}
    for name, record in check['cases'].items():
        assert record['solves'] == 3 and record['device_cleanup'] is True
        assert record['original_voltages'] == {'Si_xmin': 0., 'Si_xmax': .001}
        if name == 'normal':
            assert record['has_success_log'] is True and record['history_delta'] == 1
            assert record['returned_voltages'] == record['original_voltages']
        else:
            assert record['has_success_log'] is False and record['history_delta'] == 0 and record['field_capture_attempts'] == 0
            expected = {'Si_xmin': 0., 'Si_xmax': .002} if name == 'wrong_source_voltage' else {'Si_xmin': .1, 'Si_xmax': .001}
            assert record['returned_voltages'] == expected
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
    assert payload == prior  # 모든 노드·접점·출처 전체 기록의 동일성.
    print(json.dumps({'pass': True, 'inputs': len(summary['inputs']), 'raw_files': len(summary['outputs']) + 1,
        'blocked_contact_cases': 8, 'blocked_bias_cases': 6, 'controlled_post_success_faults': 2, 'entire_actual_export_unchanged': True, 'engine_imports': 0}))


if __name__ == '__main__':
    main(Path(sys.argv[1]))


