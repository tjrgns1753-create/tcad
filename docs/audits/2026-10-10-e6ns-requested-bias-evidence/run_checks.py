"""요청 바이어스 경계와 기존 국소 계약 검사. 원격만."""
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'docs/audits/2026-10-02-e6na-import-reduction'))
from resource_supervisor import supervise


def main():
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    out = ROOT / 'e6ns_out'
    out.mkdir(exist_ok=True)
    cases = [
        ('gui_bias', ['docs/audits/2026-10-10-e6ns-requested-bias-evidence/check_gui.py'], 120),
        ('pure_bias', ['tests/unit/test_measurement_requested_bias_mock.py'], 30),
        ('validity', ['tests/unit/test_measurement_validity_mock.py'], 30),
        ('caption', ['tests/unit/test_node_field_caption_mock.py'], 30),
        ('contacts', ['tests/unit/test_node_field_contacts_mock.py'], 30),
        ('export', ['tests/unit/test_node_field_export_mock.py'], 30),
        ('hover', ['tests/unit/test_node_field_hover_mock.py'], 30),
        ('snapshot', ['tests/unit/test_node_fields_mock.py'], 30),
        ('readout', ['tests/unit/test_field_readout_invalidation_mock.py'], 30),
    ]
    records = {}
    for name, args, budget in cases:
        log = out / (name + '.log')
        records[name] = supervise([sys.executable, '-B', *args], ROOT, log, candidate_s=budget)
        text = log.read_text(encoding='utf-8', errors='replace')
        log.write_text(text.replace(str(ROOT), '<REPO>').replace(str(Path.home()), '<USERPROFILE>'),
                       encoding='utf-8', newline='\n')
    passed = all(r['status'] == 'COMPLETED' and r['cleanup_ok'] and r.get('exit_code') == 0
                 for r in records.values())
    (out / 'tests.json').write_text(json.dumps({'pass': passed, 'steps': records}, indent=2), encoding='utf-8')
    print(json.dumps({'pass': passed, 'codes': {n: r.get('exit_code') for n, r in records.items()}}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
