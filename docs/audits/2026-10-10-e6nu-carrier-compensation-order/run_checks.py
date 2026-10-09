"""원격 전용: 실제 12요청과 엔진 없는 계약 대조. 중복 계산 없음."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
from resource_supervisor import supervise


def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    out=ROOT/'e6nu_out'
    out.mkdir(exist_ok=True)
    records={}
    for name,args,budget in (
        ('matrix',['docs/audits/2026-10-10-e6nu-carrier-compensation-order/check_matrix.py'],180),
        ('judge',['docs/audits/2026-10-10-e6nu-carrier-compensation-order/test_contract.py'],30),
        ('bias',['tests/unit/test_measurement_requested_bias_mock.py'],30),
        ('caption',['tests/unit/test_node_field_caption_mock.py'],30),
        ('no_resurrection',['tests/unit/test_wafer_state_v2_fail_closed_no_resurrection_mock.py'],30),
    ):
        log=out/(name+'.log')
        records[name]=supervise([sys.executable,'-B',*args],ROOT,log,candidate_s=budget)
        text=log.read_text(encoding='utf-8',errors='replace')
        log.write_text(text.replace(str(ROOT),'<REPO>').replace(str(Path.home()),'<USERPROFILE>'),encoding='utf-8',newline='\n')
    passed=all(r['status']=='COMPLETED' and r['cleanup_ok'] and r.get('exit_code')==0 for r in records.values())
    (out/'tests.json').write_text(json.dumps({'pass':passed,'steps':records},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'codes':{n:r.get('exit_code') for n,r in records.items()}}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
