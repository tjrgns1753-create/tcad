"""고정 기준 remote GUI + 전체 tracked unit. 물리 capability 승인 아님."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = '53e532d083d6e64d7d923033b70223b985db3fd8a92273a5f454966be05d9210'
CONTROLS = ['tests/integration/test_transport_evidence_gui_real.py',
            'tests/integration/test_gui_doping_donor_acceptor_real.py',
            'tests/integration/test_measurement_canonical_state_gate_real.py',
            'tests/integration/test_gui_headless_no_modal_hang_real.py']


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    assert hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == PLAN_SHA
    names = subprocess.check_output(['git', 'ls-files', 'tests/unit/test_*.py'], cwd=ROOT, text=True).splitlines()
    assert len(names) == len(set(names)) == 88 and 'tests/unit/test_transport_evidence_mock.py' in names
    baseline = json.loads((ROOT/'docs/audits/2026-10-10-e6nag-barrier-unit-regression/MANIFEST.json').read_text(encoding='utf-8'))
    for row in baseline['tests']:
        assert row['path'] in names
        assert hashlib.sha256((ROOT/row['path']).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == row['lf_sha256']
    sys.path.insert(0, str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
    sys.path.insert(0, str(ROOT/'remote'))
    from resource_supervisor import supervise
    from run_profile import Sanitizer
    sanitizer = Sanitizer()
    out = ROOT/'e6nah_out'
    out.mkdir(exist_ok=True)
    records = {}
    for path in CONTROLS + names:
        log = out/(Path(path).stem+'.log')
        r = supervise([sys.executable, '-B', path], ROOT, log, candidate_s=120 if path in CONTROLS else 60)
        text = sanitizer.clean(log.read_text(encoding='utf-8', errors='replace'))
        log.write_text(text, encoding='utf-8', newline='\n')
        r.update(log_file=log.name, log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                 input_lf_sha256=hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                 skip_detected=('SKIPPED:' in text or 'SKIP:' in text))
        records[path] = r
        (out/'records.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        print(json.dumps({'file': path, 'status': r['status'], 'rc': r.get('exit_code')}), flush=True)
    passed = len(records) == 92 and all(r['status'] == 'COMPLETED' and r.get('exit_code') == 0
                and r['cleanup_ok'] and not r['skip_detected'] for r in records.values())
    (out/'verdict.json').write_text(json.dumps({'pass': passed, 'files': len(records),
        'scope': 'MODEL_EVIDENCE_NOT_MATERIAL_CALIBRATION', 'plan_sha': PLAN_SHA}), encoding='utf-8')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
