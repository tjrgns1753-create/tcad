"""고정 원격 소스와 원시 bytes를 엔진 없이 독립 대조한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
SHA='84eb856f19db6e635d28845dfec13e7b2748138a'
RUN='37565421867'
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
def main(root):
    s=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert s['source']['github_sha']==s['source']['git_head']==SHA
    assert s['source']['run_id']==RUN
    assert s['status']=='PASS' and s['exit_code']==0 and not s['omitted_outputs']
    assert s['runner']['runner_environment']=='github-hosted'
    repo=Path(__file__).resolve().parents[3]
    env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1')
    for r in s['inputs']:
        blob=subprocess.check_output(['git','show',SHA+':'+r['path']],cwd=repo,env=env)
        lf=blob.replace(b'\r\n',b'\n')
        assert any(len(v)==r['bytes'] and hashlib.sha256(v).hexdigest()==r['sha256'] for v in (blob,lf,lf.replace(b'\n',b'\r\n')))
    for r in s['outputs']+[s['log']]:
        path=root/('outputs/'+r['path'] if 'path' in r else r['file'])
        data=path.read_bytes()
        assert len(data)==r['bytes'] and hashlib.sha256(data).hexdigest()==r['sha256']
    out=root/'outputs/e6nl_out'
    t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True
    assert set(t['steps'])=={'export','bundle','units','entry_gate','existing_gui'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    g=json.loads((out/'export.json').read_text(encoding='utf-8'))
    assert g['pass'] is g['source_sha_verified'] is g['csv_sha_verified'] is g['full_bias_preserved'] is True
    assert g['current_unit']=='A/cm' and g['gui_mock_dc']=='SYNTHETIC_NOT_PHYSICS_EVIDENCE'
    import csv
    payload=json.loads((out/'한국어.csv.metadata.json').read_text(encoding='utf-8'))
    csv_path=out/'한국어.csv'
    md=payload['metadata']
    assert md['current_unit']=='A/cm' and md['device_dimension']==2
    assert md['export_evidence']['csv_sha256']==hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source_input=next(r for r in s['inputs'] if r['path']=='tests/unit/test_measurement_entry_point_gate_mock.py')
    assert md['source_evidence']['mesh_sha256']==source_input['sha256']
    assert md['source_evidence']['canonical_record']=='GUI_SESSION_ONLY'
    assert md['verification_scope']=='INPUT_SOURCE_MATCH_ONLY_NOT_GENERAL_PHYSICS_APPROVAL'
    assert payload['points'][0]['converged'] is True and payload['points'][0]['voltages']['Gate']==1.
    with csv_path.open(encoding='utf-8',newline='') as stream: rows=list(csv.reader(stream))
    assert rows[0]==['sweep_voltage_V','I_Drain_A_per_cm','I_Source_A_per_cm']
    assert float(rows[1][0])==payload['points'][0]['voltages']['Drain']==.1
    assert float(rows[1][1])==payload['points'][0]['currents']['Drain']==1e-6
    assert float(rows[1][2])==payload['points'][0]['currents']['Source']==-1e-6
    control=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert control['pass'] is True and all(r['pass'] is True for r in control['checks'])
    print(json.dumps({'pass':True,'source_inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'steps':len(t['steps']),'engine_imports':0}))
if __name__=='__main__': main(Path(sys.argv[1]))
