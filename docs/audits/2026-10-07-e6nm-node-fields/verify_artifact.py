"""엔진 없이 고정 실행 소스·원시 파일·노드 배열을 독립 검증한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
SHA='1b03e34fd3a80eb830ceec1c97124bf5c61ec18e'
RUN='37570252227'
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
    out=root/'outputs/e6nm_out'
    t=json.loads((out/'tests.json').read_text(encoding='utf-8'))
    assert t['pass'] is True and set(t['steps'])=={'fields','pure','validity','entry_gate','uniform_control'}
    assert all(r['status']=='COMPLETED' and r['cleanup_ok'] is True and r['exit_code']==0 for r in t['steps'].values())
    f=json.loads((out/'fields.json').read_text(encoding='utf-8'));a=f['snapshot'];xy=a['xy_um']
    assert f['pass'] is f['device_cleanup'] is f['capture_equals_live_api'] is f['failed_retry_has_no_fields'] is True
    assert f['solves']==3 and 0<len(xy)<=2000
    assert set(f['rendered'])=={'potential','electron','hole'}
    for k in f['rendered']:
        assert f['rendered'][k]['nodes']==len(xy)==len(a[k]) and all(math.isfinite(v) for v in a[k])
        assert any('No interpolation' in v for v in f['rendered'][k]['notes'])
    assert all(len(p)==2 and all(math.isfinite(v) for v in p) for p in xy)
    assert min(a['electron'])>0 and min(a['hole'])>0
    xs=[p[0] for p in xy];xmin,xmax=min(xs),max(xs)
    left=[v for x,v in zip(xs,a['potential']) if x==xmin];ref=sum(left)/len(left)
    error=max(abs(v-(ref+.001*(x-xmin)/(xmax-xmin))) for x,v in zip(xs,a['potential']))/.001
    assert error<=1e-6 and abs(error-f['psi_linear_relative_error'])<=1e-12
    c=json.loads((out/'gui_unit_contract.json').read_text(encoding='utf-8'))
    assert c['pass'] is True and all(r['pass'] is True for r in c['checks'])
    print(json.dumps({'pass':True,'inputs':len(s['inputs']),'raw_files':len(s['outputs'])+1,'nodes':len(xy),'engine_imports':0}))
if __name__=='__main__':main(Path(sys.argv[1]))
