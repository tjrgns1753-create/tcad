"""원격 전용 대표 GUI 및 기존 gate/단위 회귀. 전체 회귀 아님."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
from resource_supervisor import supervise

def main():
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    out=ROOT/'e6ng_out'; out.mkdir(exist_ok=True)
    steps=[('view_mock',['tests/unit/test_pn_reference_view_mock.py'],30),
           ('gui_reference',['tests/integration/test_pn_reference_gui_real.py',str(out)],180),
           ('canonical_gate',['tests/unit/test_measurement_canonical_state_gate_mock.py'],30),
           ('current_units',['tests/unit/test_current_unit_contract_mock.py'],60),
           ('existing_gui',['tests/integration/test_gui_current_unit_contract_real.py',str(out)],120)]
    records={}
    for name,args,budget in steps:
        records[name]=supervise([sys.executable,'-B',*args],ROOT,out/(name+'.log'),candidate_s=budget)
    passed=all(v['status']=='COMPLETED' and v['cleanup_ok'] is True and v.get('exit_code')==0 for v in records.values())
    (out/'tests.json').write_text(json.dumps({'pass':passed,'steps':records},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'steps':{k:v.get('exit_code') for k,v in records.items()}},indent=2))
    return 0 if passed else 1

if __name__=='__main__':
    raise SystemExit(main())
