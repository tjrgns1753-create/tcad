"""원격 hover 원시 증거를 엔진 없이 독립 대조한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
SHA='dbcce97443dc33e3371418510c17c8cd2c41d1cf'
RUN='37570833575'
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
def main(root):
    s=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert s['source']['github_sha']==s['source']['git_head']==SHA and s['source']['run_id']==RUN
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
        b=path.read_bytes();assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    out=root/'outputs/e6nn_out'
    t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True and set(t['steps'])=={'hover','pure','snapshot','doping_hover','gate_control'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    f=json.loads((out/'hover.json').read_text(encoding='utf-8'))
    assert f['pass'] is f['reset_cleared'] is f['outside_no_value'] is f['stale_no_value'] is f['device_cleanup'] is True
    assert f['solves']==3 and set(f['readouts'])=={'potential','electron','hole'}
    for name,unit in [('potential','V'),('electron','cm^-3'),('hole','cm^-3')]:
        r=f['readouts'][name];assert r['node_index']==0 and all(math.isfinite(v) for v in r['xy_um'])
        assert math.isfinite(r['raw_value']) and f"{r['raw_value']:.6e} {unit}" in r['text'] and '보간 아님' in r['text']
    c=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert c['pass'] is True and all(r['pass'] is True for r in c['checks'])
    print(json.dumps({'pass':True,'inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'engine_imports':0}))
if __name__=='__main__':main(Path(sys.argv[1]))
