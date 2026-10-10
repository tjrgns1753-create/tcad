import hashlib
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = '17bbb79400f32fa55b79cbc0dc71cf053cd2d4940858c40697f3d082ade7c80d'
FILES = ['tests/unit/test_field_color_range_mock.py', 'tests/unit/test_field_model_scope_mock.py',
         'tests/unit/test_node_fields_mock.py', 'tests/unit/test_node_field_caption_mock.py',
         'tests/integration/test_field_model_scope_gui_real.py', 'tests/integration/test_transport_evidence_gui_real.py']


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    assert hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == PLAN_SHA
    sys.path.insert(0, str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
    sys.path.insert(0, str(ROOT/'remote'))
    from resource_supervisor import supervise
    from run_profile import Sanitizer
    out = ROOT/'e6nak_out'
    out.mkdir(exist_ok=True)
    records = {}
    for path in FILES:
        log = out/(Path(path).stem+'.log')
        row = supervise([sys.executable, '-B', path], ROOT, log, candidate_s=120)
        log.write_text(Sanitizer().clean(log.read_text(encoding='utf-8', errors='replace')), encoding='utf-8', newline='\n')
        row.update(log_file=log.name, log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                   input_lf_sha256=hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest())
        records[path] = row
        (out/'records.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        assert row['status'] == 'COMPLETED' and row['exit_code'] == 0 and row['cleanup_ok'] is True, row
        print(json.dumps({'file': path, 'status': 'PASS'}), flush=True)
    (out/'verdict.json').write_text(json.dumps({'pass': True, 'files': 6, 'plan_sha': PLAN_SHA,
        'scope': 'COLOR_DISCLOSURE_NOT_NOISE_FILTER_OR_CALIBRATION'}), encoding='utf-8')


if __name__ == '__main__': main()
