"""고정 원격 소스와 원시 bytes를 엔진 없이 독립 대조한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
SHA='fc296edbb8e62cf3544b882b0a876cea5d4a1a53'
RUN='37486908105'
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
    out=root/'outputs/e6nk_out'
    t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True
    assert set(t['steps'])=={'context','source','validity','entry_gate','existing_gui'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    g=json.loads((out/'context.json').read_text(encoding='utf-8'))
    assert g['pass'] is g['same_source_export'] is g['stale_export_blocked'] is g['reset_context_cleared'] is True
    assert g['export_control']=='SYNTHETIC'
    assert set(g['cases'])=={'state','pin','mesh_bytes','missing_context'}
    assert all(r['solves']==r['doping_writes']==r['devices_remaining']==0 for r in g['cases'].values())
    control=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert control['pass'] is True and all(r['pass'] is True for r in control['checks'])
    print(json.dumps({'pass':True,'source_inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'steps':len(t['steps']),'engine_imports':0}))
if __name__=='__main__': main(Path(sys.argv[1]))
