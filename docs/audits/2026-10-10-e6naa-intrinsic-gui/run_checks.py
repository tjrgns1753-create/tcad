"""원격 child 단독 실행과 자원 정리. 상위 프로세스는 엔진을 import하지 않는다."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'remote'),str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction')]
from resource_supervisor import supervise
from run_profile import Sanitizer

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
    out=ROOT/'e6naa_out'; out.mkdir(exist_ok=True)
    steps={}; sanitizer=Sanitizer()
    for name,file,budget in (
        ('contract','tests/unit/test_intrinsic_measurement_contract_mock.py',30),
        ('missing','tests/unit/test_measurement_missing_profile_status_mock.py',30),
        ('bias','tests/unit/test_measurement_requested_bias_mock.py',30),
        ('gui','docs/audits/2026-10-10-e6naa-intrinsic-gui/check_gui.py',180),
        ('canonical','tests/integration/test_measurement_canonical_state_gate_real.py',180)):
        log=out/(name+'.log')
        steps[name]=supervise([sys.executable,'-B',file],ROOT,log,candidate_s=budget)
        log.write_text(sanitizer.clean(log.read_text(encoding='utf-8',errors='replace')),encoding='utf-8',newline='\n')
        (out/'steps.json').write_text(json.dumps(steps,indent=2),encoding='utf-8')
    ok=all(s['status']=='COMPLETED' and s.get('exit_code')==0 and s['cleanup_ok'] for s in steps.values())
    print(json.dumps({'pass':ok,'steps':steps})); return 0 if ok else 1

if __name__=='__main__': raise SystemExit(main())
