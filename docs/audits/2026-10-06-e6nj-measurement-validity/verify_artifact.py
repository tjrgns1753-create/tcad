"""고정 원격 소스와 원시 bytes를 엔진 없이 독립 대조한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
SHA='2bab11c33d0df69a5e094a9ce973e62bcbe09dfa'
RUN='37465658115'
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
    out=root/'outputs/e6nj_out'
    t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True
    assert set(t['steps'])=={'gui','boundary','canonical_gate','entry_gate','existing_gui'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    g=json.loads((out/'gui.json').read_text(encoding='utf-8'))
    assert g['pass'] is g['failed_retry_no_export'] is True
    assert set(g['cases'])=={'nan','inf','-inf','bad'}
    assert all(r['engine_prepare_attempts']==0 and r['previous_result_cleared'] is True for r in g['cases'].values())
    assert set(g['controlled_output_faults'])=={'nan_current','not_converged'}
    assert all(r['attempted_solves']>0 and r['devices_remaining']==0 and r['success_block_absent'] is True for r in g['controlled_output_faults'].values())
    control=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert control['pass'] is True and all(r['pass'] is True for r in control['checks'])
    print(json.dumps({'pass':True,'source_inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'steps':len(t['steps']),'engine_imports':0}))
if __name__=='__main__': main(Path(sys.argv[1]))
