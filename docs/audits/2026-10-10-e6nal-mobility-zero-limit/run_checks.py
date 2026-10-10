import hashlib
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = '092d7042ee87364d4e32a051a88cde090e73dc5d28f0ee20c2b060635eab586e'


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    assert hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == PLAN_SHA
    sys.path.insert(0, str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
    sys.path.insert(0, str(ROOT/'remote'))
    from resource_supervisor import supervise
    from run_profile import Sanitizer
    from judge import judge, EXPECTED
    out = ROOT/'e6nal_out'
    out.mkdir(exist_ok=True)
    records = {}
    for label in EXPECTED:
        log = out/(label+'.log')
        row = supervise([sys.executable, '-B', str(HERE/'probe.py'), label], ROOT, log, candidate_s=45)
        log.write_text(Sanitizer().clean(log.read_text(encoding='utf-8', errors='replace')), encoding='utf-8', newline='\n')
        row['log_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
        records[label] = row
        (out/'records.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0 and row['cleanup_ok'] is True, row
    rows = {label: json.loads((out/(label+'.json')).read_text(encoding='utf-8')) for label in EXPECTED}
    verdict = judge(rows, PLAN_SHA)
    (out/'verdict.json').write_text(json.dumps({'evidence_complete': True, 'model_evaluation': verdict,
        'candidate': 'AUDIT_ONLY_CONTINUOUS_EXTENSION', 'production_changed': False,
        'material_calibration': 'NOT_VALIDATED'}, indent=2), encoding='utf-8')
    print(json.dumps(verdict))


if __name__ == '__main__': main()
