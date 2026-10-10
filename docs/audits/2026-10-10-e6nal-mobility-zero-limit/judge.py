import importlib.util
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('official_mobility_base_judge', ROOT/'docs/audits/2026-10-10-e6naj-official-mobility/judge.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
EXPECTED = base.EXPECTED


def judge(rows, plan_sha):
    result = base.judge(rows, plan_sha)
    original_dir = ROOT/'docs/audits/2026-10-10-e6naj-official-mobility/raw/remote-run-87/outputs/e6naj_out'
    import json
    for label, row in rows.items():
        original = json.loads((original_dir/(label+'.json')).read_text(encoding='utf-8'))
        assert row['helper_source_lf_sha256'] == original['helper_source_lf_sha256']
        assert row['candidate'] == 'AUDIT_ONLY_CONTINUOUS_EXTENSION'
        assert row['replaced_models'] == ['Z_D', 'Z_A']
        assert row['status'] == 'NUMERIC_EVALUABLE'
        for name, value in zip(('Z_D', 'Z_A'), EXPECTED[label][:2]):
            if value == 0.: assert row['models'][name]['values'] == [1.]*4
        if label == 'BOTH_POSITIVE_CONTROL':
            assert row['positive_baseline_equal_128ulp'] is True
            for name in row['models']:
                actual = row['models'][name]['values']
                old = original['models'][name]['values']
                assert all(abs(a-b) <= 128*math.ulp(b) for a,b in zip(actual, old))
    return result
