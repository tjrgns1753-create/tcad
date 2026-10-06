"""원격 대표 GUI/source/gate 검사. 전체 회귀 아님."""
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
    out=ROOT/'e6nh_out'; out.mkdir(exist_ok=True)
    cases=[('before',['docs/audits/2026-10-06-e6nh-canvas-source-contract/check_canvas.py','--before'],60),
           ('canvas',['docs/audits/2026-10-06-e6nh-canvas-source-contract/check_canvas.py'],120),
           ('source_mock',['tests/unit/test_gui_canvas_source_contract_mock.py'],30),
           ('canonical_gate',['tests/unit/test_measurement_canonical_state_gate_mock.py'],30),
           ('existing_gui',['tests/integration/test_gui_current_unit_contract_real.py',str(out)],120),
           ('pn_reference',['tests/unit/test_pn_reference_view_mock.py'],30)]
    records={}
    for name,args,budget in cases:
        records[name]=supervise([sys.executable,'-B',*args],ROOT,out/(name+'.log'),candidate_s=budget)
        log=out/(name+'.log')
        value=log.read_text(encoding='utf-8',errors='replace')
        log.write_text(value.replace(str(ROOT),'<REPO>').replace(str(Path.home()),'<USERPROFILE>'),encoding='utf-8',newline='\n')
    passed=all(r['status']=='COMPLETED' and r['cleanup_ok'] and r.get('exit_code')==0 for r in records.values())
    (out/'tests.json').write_text(json.dumps({'pass':passed,'steps':records},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'codes':{n:r.get('exit_code') for n,r in records.items()}}))
    return 0 if passed else 1

if __name__=='__main__':
    raise SystemExit(main())
