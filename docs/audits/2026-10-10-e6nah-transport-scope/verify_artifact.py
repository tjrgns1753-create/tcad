"""엔진 없이 source/input/output/log와 실제 GUI 증거를 독립 대조."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = '157d382918f309fcbd7e9a97051113fbcd04605b'
RUN = '38056456986'
PLAN_SHA = '53e532d083d6e64d7d923033b70223b985db3fd8a92273a5f454966be05d9210'


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise RuntimeError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(forbid)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def judge_metrics(metrics):
    assert set(metrics) == {'n', 'p', 'intrinsic', 'missing', 'nan'}
    expected_units = {'T': 'K', 'mu_n': 'cm^2/(V*s)', 'mu_p': 'cm^2/(V*s)', 'n_i': 'cm^-3',
                      'taun': 's', 'taup': 's', 'ElectronCharge': 'C', 'Permittivity': 'F/cm',
                      'V_t': 'V', 'n1': 'cm^-3', 'p1': 'cm^-3'}
    for key in ('n', 'p', 'intrinsic'):
        row = metrics[key]
        assert row['solve_calls'] == 3 and row['same_gui_and_export'] is True
        record = row['transport_model']
        assert record['capture_api'] == 'devsim.get_parameter' and record['material_calibration'] == 'NOT_VALIDATED'
        assert record['capture_stage'] == 'POST_DD_SETUP_PRE_DD_SOLVE'
        p = record['parameters']
        assert set(p) == set(expected_units)
        import math
        for name, unit in expected_units.items():
            assert p[name]['unit'] == unit and math.isfinite(p[name]['value']) and p[name]['value'] > 0
        assert p['T']['value'] == 300. and p['mu_n']['value'] == 400. and p['mu_p']['value'] == 200.
        assert p['n_i']['value'] == p['n1']['value'] == p['p1']['value'] == 1e10
        assert p['taun']['value'] == p['taup']['value'] == 1e-8
        if key != 'intrinsic':
            expected = .0016 if key == 'n' else .0004
            assert abs(row['currents'][0] / expected - 1) <= 1e-6
    for key in ('missing', 'nan'):
        assert metrics[key] == {'solve_calls': 1, 'reported_currents': 0, 'fields_cleared': True}


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
    out = raw/'outputs/e6nah_out'
    records = json.loads((out/'records.json').read_text(encoding='utf-8'))
    units = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', SOURCE, '--', 'tests/unit'], cwd=ROOT, text=True).splitlines()
    units = {p for p in units if Path(p).name.startswith('test_') and p.endswith('.py')}
    controls = {'tests/integration/test_transport_evidence_gui_real.py',
                'tests/integration/test_gui_doping_donor_acceptor_real.py',
                'tests/integration/test_measurement_canonical_state_gate_real.py',
                'tests/integration/test_gui_headless_no_modal_hang_real.py'}
    assert len(units) == 88 and set(records) == units | controls
    for path, row in records.items():
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0 and row['cleanup_ok'] is True and row['skip_detected'] is False
        blob = subprocess.check_output(['git', 'show', SOURCE+':'+path], cwd=ROOT)
        assert sha(blob.replace(b'\r\n', b'\n')) == row['input_lf_sha256']
        assert sha((out/row['log_file']).read_bytes()) == row['log_sha256']
    old = json.loads((ROOT/'docs/audits/2026-10-10-e6nag-barrier-unit-regression/raw/remote-run-84/outputs/e6nag_out/records.json').read_text(encoding='utf-8'))
    assert len(old) == 87
    for path, row in old.items():
        assert row['input_lf_sha256'] == records[path]['input_lf_sha256']
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0
    log = (out/'test_transport_evidence_gui_real.log').read_text(encoding='utf-8')
    rows = [json.loads(line[len('TRANSPORT_METRICS '):]) for line in log.splitlines() if line.startswith('TRANSPORT_METRICS ')]
    assert len(rows) == 1
    judge_metrics(rows[0])
    mutations = []
    for label in ('missing_unit', 'false_calibration', 'fault_reported_current', 'missing_fault', 'nan_parameter'):
        m = copy.deepcopy(rows[0])
        if label == 'missing_unit': del m['n']['transport_model']['parameters']['mu_n']['unit']
        elif label == 'false_calibration': m['p']['transport_model']['material_calibration'] = 'VALIDATED'
        elif label == 'fault_reported_current': m['missing']['reported_currents'] = 1
        elif label == 'missing_fault': del m['nan']
        else: m['intrinsic']['transport_model']['parameters']['taun']['value'] = float('nan')
        try: judge_metrics(m)
        except (AssertionError, KeyError, ValueError): mutations.append(label)
        else: raise AssertionError('FALSE_GREEN: '+label)
    verdict = json.loads((out/'verdict.json').read_text(encoding='utf-8'))
    assert verdict == {'pass': True, 'files': 92, 'scope': 'MODEL_EVIDENCE_NOT_MATERIAL_CALIBRATION', 'plan_sha': PLAN_SHA}
    print(json.dumps({'pass': True, 'files': 92, 'same_87_unit_inputs_pass_to_pass': 87,
                      'mutants_blocked': mutations, 'source_sha': SOURCE, 'run_id': RUN,
                      'seconds': summary['duration_s'], 'outputs_verified': len(summary['outputs'])}, indent=2))


if __name__ == '__main__':
    main()
