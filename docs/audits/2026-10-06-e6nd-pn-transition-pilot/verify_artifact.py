"""독립 로컬 재판정: artifact 바이트 해시와 실제 소스 SHA를 확인한다."""
import hashlib
import json
from pathlib import Path
import sys

import pilot
from judge import judge

EXPECTED_SOURCES = {'e6nd_pn_transition_pilot':'0aae0a35bcfa38ceca374556199a451dd01c3076',
                    'e6nd_pn_fine_diagnostic':'7b2d2178597ef042fcd9b068df2018a797dafa1d'}


def main(path):
    path = Path(path)
    summary = json.loads((path/'summary.json').read_text())
    expected = EXPECTED_SOURCES.get(summary['profile'])
    if expected is None or summary['source']['github_sha']!=expected or summary['omitted_outputs'] or summary['log_truncated']:
        raise ValueError('ARTIFACT_IDENTITY_OR_COMPLETENESS_FAIL')
    verified = 0
    for file,r in [(path/'run.log',summary['log'])]+[(path/'outputs'/r['path'],r) for r in summary['outputs']]:
        if file.stat().st_size!=r['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=r['sha256']:
            raise ValueError('RAW_ARTIFACT_HASH_FAIL')
        verified += 1
    fine = summary['profile']=='e6nd_pn_fine_diagnostic'
    out = path/('outputs/e6nd_fine_out' if fine else 'outputs/e6nd_out')
    stored = json.loads((out/'result.json').read_text())
    if fine:
        from fine_pilot import evaluate
        recomputed = evaluate(out)
    else:
        recomputed = judge(out)
    # 원래 수치 기준은 그대로 두고, 추가한 배열 관계 검사만 별도로 평가한다.
    stored_checks = {c['name']:c['pass'] for c in stored['checks']}
    new_checks = {c['name']:c['pass'] for c in recomputed['checks']}
    if any(name not in new_checks or new_checks[name]!=value for name,value in stored_checks.items()):
        raise ValueError('RECOMPUTED_ORIGINAL_CHECK_DIFFERS')
    if stored['metrics']!=recomputed['metrics'] or stored['problems']!=recomputed['problems'] or stored['production_gate_released'] is not False:
        raise ValueError('RECOMPUTED_RAW_METRICS_DIFFERS')
    should_succeed = stored['status'] in ('PILOT_PASS','FINE_PILOT_PASS')
    if (type(summary['exit_code']) is not int or summary['exit_code']!=(0 if should_succeed else 1)
            or summary['status']!=('PASS' if should_succeed else 'FAIL') or stored['status']!=recomputed['status']):
        raise ValueError('EXIT_STATUS_OR_RECOMPUTED_VERDICT_CONFLICT')
    print(json.dumps({'artifact_files_verified':verified,'source_sha':expected,'remote_status':summary['status'],'remote_exit_code':summary['exit_code'],'stored_status':stored['status'],'recomputed':recomputed},indent=2))


if __name__=='__main__':
    main(sys.argv[1])
