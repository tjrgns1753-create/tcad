"""화면 범위와 실제 물성 대조군의 원격 증거를 엔진 없이 검사."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = '5c53b146c13044e14b1cc5c0d304d12a53fcaa0c'
RUN = '38058145706'
PLAN_SHA = '17bbb79400f32fa55b79cbc0dc71cf053cd2d4940858c40697f3d082ade7c80d'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canvas = load('canvas_evidence_judge', ROOT/'docs/audits/2026-10-10-e6nai-field-model-scope/verify_artifact.py')
transport = load('transport_evidence_judge', ROOT/'docs/audits/2026-10-10-e6nah-transport-scope/verify_artifact.py')
driver = load('color_driver_contract', HERE/'run_checks.py')
sha = lambda b: hashlib.sha256(b).hexdigest()


def judge(metrics):
    canvas.judge_canvas(metrics)
    for row in metrics.values():
        for layer, item in row['layers'].items():
            text = item['caption']
            assert '자동 색 확대; 물리적 유의성 보장 아님.' in text
            assert ('상대 범위는 전위 기준 의존' in text) == (layer == 'potential')
            match = re.search(r'선형색 파랑=([^,]+), 빨강=([^ ]+) ', text)
            assert match
            lo, hi = map(float, match.groups())
            assert math.isfinite(lo) and math.isfinite(hi) and hi >= lo
            assert match.groups() == (format(lo, '.17g'), format(hi, '.17g'))
            unit = 'V' if layer == 'potential' else 'cm^-3'
            span = hi-lo
            relative = span/max(abs(lo), abs(hi)) if max(abs(lo), abs(hi)) else 0.
            assert f'Δ={span:.17g} {unit}; 상대 범위={relative:.6g};' in text


def main():
    raw = Path(sys.argv[1])
    s = json.loads((raw/'summary.json').read_text(encoding='utf-8'))
    assert s['source']['github_sha'] == s['source']['git_head'] == SOURCE
    assert s['source']['run_id'] == RUN and s['runner']['github_hosted_confirmed'] is True
    assert s['status'] == 'PASS' and s['exit_code'] == 0 and s['omitted_outputs'] == [] and s['log_truncated'] is False
    assert sha((raw/'run.log').read_bytes()) == s['log']['sha256']
    for r in s['outputs']:
        b = (raw/'outputs'/r['path']).read_bytes()
        assert len(b) == r['bytes'] and sha(b) == r['sha256']
    for r in s['inputs']:
        b = subprocess.check_output(['git', 'show', SOURCE+':'+r['path']], cwd=ROOT)
        lf = b.replace(b'\r\n', b'\n')
        assert r['sha256'] in {sha(b), sha(lf), sha(lf.replace(b'\n', b'\r\n'))}
    out = raw/'outputs/e6nak_out'
    rows = json.loads((out/'records.json').read_text(encoding='utf-8'))
    assert set(rows) == set(driver.FILES)
    for path, r in rows.items():
        assert r['status'] == 'COMPLETED' and r['exit_code'] == 0 and r['cleanup_ok'] is True
        assert sha((out/r['log_file']).read_bytes()) == r['log_sha256']
        b = subprocess.check_output(['git', 'show', SOURCE+':'+path], cwd=ROOT)
        assert sha(b.replace(b'\r\n', b'\n')) == r['input_lf_sha256']
    metrics = json.loads((raw/'outputs/e6nai_canvas_out/metrics.json').read_text(encoding='utf-8'))
    judge(metrics)
    log = (out/'test_transport_evidence_gui_real.log').read_text(encoding='utf-8')
    records = [json.loads(line[len('TRANSPORT_METRICS '):]) for line in log.splitlines() if line.startswith('TRANSPORT_METRICS ')]
    assert len(records) == 1
    transport.judge_metrics(records[0])
    blocked = []
    for label in ('missing_span', 'wrong_span', 'false_significance', 'rounded_endpoint'):
        m = copy.deepcopy(metrics)
        item = m['n']['layers']['potential']
        if label == 'missing_span': item['caption'] = item['caption'].replace('Δ=', 'removed=')
        elif label == 'wrong_span': item['caption'] = re.sub(r'Δ=[^ ]+', 'Δ=999', item['caption'])
        elif label == 'false_significance': item['caption'] = item['caption'].replace('물리적 유의성 보장 아님', '물리적으로 검증됨')
        else: item['caption'] = re.sub(r'파랑=[^,]+', '파랑=3.5764e-01', item['caption'])
        try: judge(m)
        except (AssertionError, KeyError, ValueError): blocked.append(label)
        else: raise AssertionError('FALSE_GREEN: '+label)
    assert json.loads((out/'verdict.json').read_text(encoding='utf-8')) == {
        'pass': True, 'files': 6, 'plan_sha': PLAN_SHA, 'scope': 'COLOR_DISCLOSURE_NOT_NOISE_FILTER_OR_CALIBRATION'}
    print(json.dumps({'pass': True, 'files': 6, 'canvas_layers': 9, 'transport_control': True,
        'outputs_verified': len(s['outputs']), 'mutants_blocked': blocked, 'seconds': s['duration_s']}, indent=2))


if __name__ == '__main__': main()
