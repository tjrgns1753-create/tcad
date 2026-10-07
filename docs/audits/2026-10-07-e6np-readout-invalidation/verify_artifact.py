"""원격 실제 노드 JSON의 출처·수치·단위를 독립 대조한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
SHA='4190b5e55d7f955937a439a26842a2cdfeb98027'
RUN='37572007123'
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
def main(root):
    s=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert s['source']['github_sha']==s['source']['git_head']==SHA and s['source']['run_id']==RUN
    assert s['status']=='PASS' and s['exit_code']==0 and not s['omitted_outputs'] and s['runner']['runner_environment']=='github-hosted'
    repo=Path(__file__).resolve().parents[3]
    env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1')
    for r in s['inputs']:
        blob=subprocess.check_output(['git','show',SHA+':'+r['path']],cwd=repo,env=env)
        lf=blob.replace(b'\r\n',b'\n')
        assert any(len(v)==r['bytes'] and hashlib.sha256(v).hexdigest()==r['sha256'] for v in (blob,lf,lf.replace(b'\n',b'\r\n')))
    for r in s['outputs']+[s['log']]:
        p=root/('outputs/'+r['path'] if 'path' in r else r['file'])
        b=p.read_bytes();assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    out=root/'outputs/e6no_out';t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True and set(t['steps'])=={'export','pure','hover','snapshot','readout','gate_control'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    f=json.loads((out/'export.json').read_text(encoding='utf-8'))
    assert f['solves']==3 and f['node_count']==73
    for key in ('pass','all_arrays_equal','all_contact_bias_currents_equal','result_deepcopied','stale_blocked_before_dialog',
                'write_trace_hides_old_map','failed_retry_blocks_export','device_cleanup','redraw_cleared_readout','reset_fault_fixture_cleared_readout'):
        assert f[key] is True
    file=out/'실제노드.json';payload=json.loads(file.read_text(encoding='utf-8'))
    assert hashlib.sha256(file.read_bytes()).hexdigest()==f['file_sha256']
    assert payload['source_evidence']['mesh_sha256']==f['source_mesh_sha256']
    assert payload['source_evidence']['canonical_record']=='GUI_SESSION_ONLY'
    assert payload['physics_scope']=='SUPPORTED_MEASUREMENT_NOT_GENERAL_TCAD_APPROVAL'
    assert payload['sampling']=='ACTUAL_NODES_NO_INTERPOLATION' and payload['node_count']==73
    assert payload['units']=={'xy_um':'um','potential':'V','electron':'cm^-3','hole':'cm^-3'}
    m=payload['measurement'];assert m['converged'] is True and m['metadata']['current_unit']=='A/cm'
    assert m['metadata']['device_dimension']==2 and m['metadata']['current_normalization']=='per_out_of_plane_depth'
    assert m['voltages'][m['sweep_contact']]==.001 and len(m['currents'])==2
    for a in (m['currents'],m['voltages']):assert all(math.isfinite(v) for v in a.values())
    ref=json.loads((repo/'docs/audits/2026-10-07-e6nm-node-fields/raw/outputs/e6nm_out/fields.json').read_text(encoding='utf-8'))
    # Same supported mesh/physical parameters; compare the entire field arrays, not a selected node.
    assert payload['snapshot']==ref['snapshot']
    c=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert c['pass'] is True and all(r['pass'] is True for r in c['checks'])
    print(json.dumps({'pass':True,'inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'all_73_nodes_match_prior_live_api_evidence':True,'engine_imports':0}))
if __name__=='__main__':main(Path(sys.argv[1]))


