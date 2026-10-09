"""공식 API capability만 한 번 실행. 모델/gate/GUI 변경 없음."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
sys.path.insert(0,str(ROOT/'remote'))
from resource_supervisor import supervise
from run_profile import Sanitizer

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    out=ROOT/'e6nz_out'; out.mkdir(exist_ok=True)
    steps={}; sanitizer=Sanitizer()
    for name,file,budget in (('judge','test_judge.py',30),('api','check_api.py',180)):
        log=out/(name+'.log')
        steps[name]=supervise([sys.executable,'-B','docs/audits/2026-10-10-e6nz-intrinsic-api-capability/'+file],ROOT,log,candidate_s=budget)
        log.write_text(sanitizer.clean(log.read_text(encoding='utf-8',errors='replace')),encoding='utf-8',newline='\n')
        (out/'steps.json').write_text(json.dumps(steps,indent=2),encoding='utf-8')
    passed=all(r['status']=='COMPLETED' and r.get('exit_code')==0 and r['cleanup_ok'] for r in steps.values())
    print(json.dumps({'pass':passed,'steps':steps}))
    return 0 if passed else 1

if __name__=='__main__':
    raise SystemExit(main())
