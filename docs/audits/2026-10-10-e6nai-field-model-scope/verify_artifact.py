"""원격 캔버스 증거를 엔진 없이 독립 대조한다."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = '3641aa80cb14e121b622a023b694cb67985e6a43'
RUN = '38057101920'
PLAN_SHA = 'c4cc6d1d42edae7f632cebd7d00b51898304d90373f4762251da21302b6e6d33'


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise RuntimeError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(forbid)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def judge_canvas(metrics):
    assert set(metrics) == {'n', 'p', 'intrinsic'}
    for row in metrics.values():
        assert row['solve_calls'] == 3 and row['arrays_unchanged'] is True
        assert set(row['layers']) == {'potential', 'electron', 'hole'}
        for layer, item in row['layers'].items():
            assert item['nodes'] == 126
            assert '고정 이동도 · Boltzmann · SRH 모델 — 재료 calibration 미검증.' in item['caption']
            assert '보간 없음' in item['caption']
            assert ('원시 Potential' in item['caption']) == (layer == 'potential')
            assert item['screenshot'] in {'CAPTURED_CANVAS', 'DESKTOP_CAPTURE_UNAVAILABLE'}
            x0, y0, x1, y1 = item['bbox']
            w, h = item['canvas_size']
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h


def main():
    raw = Path(sys.argv[1])
    summary = json.loads((raw/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha'] == summary['source']['git_head'] == SOURCE
    assert summary['source']['run_id'] == RUN and summary['runner']['github_hosted_confirmed'] is True
    assert summary['status'] == 'PASS' and summary['exit_code'] == 0
    assert summary['omitted_outputs'] == [] and summary['log_truncated'] is False
    assert sha((raw/'run.log').read_bytes()) == summary['log']['sha256']
    for row in summary['outputs']:
        data = (raw/'outputs'/row['path']).read_bytes()
        assert len(data) == row['bytes'] and sha(data) == row['sha256']
    for row in summary['inputs']:
        blob = subprocess.check_output(['git', 'show', SOURCE+':'+row['path']], cwd=ROOT)
        lf = blob.replace(b'\r\n', b'\n')
        assert row['sha256'] in {sha(blob), sha(lf), sha(lf.replace(b'\n', b'\r\n'))}
    assert sha((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')) == PLAN_SHA
    out = raw/'outputs/e6nai_out'
    records = json.loads((out/'records.json').read_text(encoding='utf-8'))
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', SOURCE, '--', 'tests/unit'], cwd=ROOT, text=True).splitlines()
    units = {p for p in paths if Path(p).name.startswith('test_') and p.endswith('.py')}
    controls = {'tests/integration/test_field_model_scope_gui_real.py',
                'tests/integration/test_transport_evidence_gui_real.py',
                'tests/integration/test_gui_doping_donor_acceptor_real.py',
                'tests/integration/test_measurement_canonical_state_gate_real.py',
                'tests/integration/test_gui_headless_no_modal_hang_real.py'}
    assert len(units) == 89 and set(records) == units | controls
    for path, row in records.items():
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0 and row['cleanup_ok'] is True and row['skip_detected'] is False
        blob = subprocess.check_output(['git', 'show', SOURCE+':'+path], cwd=ROOT)
        assert sha(blob.replace(b'\r\n', b'\n')) == row['input_lf_sha256']
        assert sha((out/row['log_file']).read_bytes()) == row['log_sha256']
    old = json.loads((ROOT/'docs/audits/2026-10-10-e6nah-transport-scope/raw_initial/remote-run-85/outputs/e6nah_out/records.json').read_text(encoding='utf-8'))
    old_units = {p: r for p, r in old.items() if p.startswith('tests/unit/')}
    assert len(old_units) == 88
    for path, row in old_units.items():
        assert row['input_lf_sha256'] == records[path]['input_lf_sha256']
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0
    metrics = json.loads((raw/'outputs/e6nai_canvas_out/metrics.json').read_text(encoding='utf-8'))
    judge_canvas(metrics)
    pngs = []
    for label, row in metrics.items():
        for layer, item in row['layers'].items():
            if item['screenshot'] == 'CAPTURED_CANVAS':
                p = raw/'outputs/e6nai_canvas_out'/(label+'_'+layer+'.png')
                assert p.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                pngs.append(p.name)
    blocked = []
    for label in ('missing_layer', 'false_scope', 'changed_array', 'clipped_note', 'extra_solve'):
        m = copy.deepcopy(metrics)
        if label == 'missing_layer': del m['n']['layers']['hole']
        elif label == 'false_scope': m['n']['layers']['potential']['caption'] = 'calibration 검증됨'
        elif label == 'changed_array': m['p']['arrays_unchanged'] = False
        elif label == 'clipped_note': m['p']['layers']['hole']['bbox'][0] = -1
        else: m['intrinsic']['solve_calls'] = 4
        try: judge_canvas(m)
        except (AssertionError, KeyError, ValueError): blocked.append(label)
        else: raise AssertionError('FALSE_GREEN: '+label)
    assert json.loads((out/'verdict.json').read_text(encoding='utf-8')) == {
        'pass': True, 'files': 94, 'plan_sha': PLAN_SHA, 'scope': 'ACTUAL_CANVAS_MODEL_SCOPE_NOT_MATERIAL_CALIBRATION'}
    print(json.dumps({'pass': True, 'files': 94, 'old_unit_inputs_unchanged': 88,
        'canvas_layers': 9, 'screenshots': pngs, 'mutants_blocked': blocked,
        'outputs_verified': len(summary['outputs']), 'seconds': summary['duration_s']}, indent=2))


if __name__ == '__main__': main()
