"""대표 표시·gate 대조군만 원격에서 실행한다."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
from resource_supervisor import supervise

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
    out=ROOT/'e6ni_out'; out.mkdir(exist_ok=True)
    cases=[('depth',['docs/audits/2026-10-06-e6ni-depth-doping-display/check_depth.py'],120),
           ('invalid',['docs/audits/2026-10-06-e6ni-depth-doping-display/check_invalid.py'],60),
           ('source',['tests/unit/test_gui_depth_doping_mock.py'],30),
           ('canvas_source',['tests/unit/test_gui_canvas_source_contract_mock.py'],30),
           ('hover_legacy',['tests/unit/test_doping_unsupported_hover_note_mock.py'],30),
           ('canonical_gate',['tests/unit/test_measurement_canonical_state_gate_mock.py'],30),
           ('existing_gui',['tests/integration/test_gui_current_unit_contract_real.py',str(out)],120)]
    records={}
    for name,args,budget in cases:
        log=out/(name+'.log')
        records[name]=supervise([sys.executable,'-B',*args],ROOT,log,candidate_s=budget)
        value=log.read_text(encoding='utf-8',errors='replace')
        log.write_text(value.replace(str(ROOT),'<REPO>').replace(str(Path.home()),'<USERPROFILE>'),encoding='utf-8',newline='\n')
    passed=all(r['status']=='COMPLETED' and r['cleanup_ok'] and r.get('exit_code')==0 for r in records.values())
    (out/'tests.json').write_text(json.dumps({'pass':passed,'steps':records},indent=2),encoding='utf-8')
    print(json.dumps({'pass':passed,'codes':{n:r.get('exit_code') for n,r in records.items()}}))
    return 0 if passed else 1

if __name__=='__main__': raise SystemExit(main())
