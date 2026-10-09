"""실행 출처·원본과 전체 노드를 엔진 없이 독립 대조한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
SHA='79ea8e3a56034f28eaa832e53b8f2e3c370b46a4'
RUN='37981805856'
ROOT=Path(__file__).resolve().parents[3]

def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)

def blob(path):
    return subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'show',SHA+':'+path],cwd=ROOT,
        env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1'))

def main(raw):
    summary=json.loads((raw/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha']==summary['source']['git_head']==SHA
    assert summary['source']['run_id']==RUN and summary['runner']['runner_environment']=='github-hosted'
    assert summary['status']=='PASS' and summary['exit_code']==0 and not summary['omitted_outputs']
    for record in summary['inputs']:
        b=blob(record['path']); lf=b.replace(b'\r\n',b'\n')
        assert any(len(v)==record['bytes'] and hashlib.sha256(v).hexdigest()==record['sha256'] for v in (b,lf,lf.replace(b'\n',b'\r\n'))), record['path']
    for record in summary['outputs']+[summary['log']]:
        p=raw/('outputs/'+record['path'] if 'path' in record else record['file']); b=p.read_bytes()
        assert len(b)==record['bytes'] and hashlib.sha256(b).hexdigest()==record['sha256']
    out=raw/'outputs/e6nz_out'; data=json.loads((out/'records.json').read_text(encoding='utf-8'))
    plan=blob('docs/audits/2026-10-10-e6nz-intrinsic-api-capability/PLAN.md').replace(b'\r\n',b'\n')
    assert hashlib.sha256(plan).hexdigest()==data['plan_sha']
    namespace={}; exec(compile(blob('docs/audits/2026-10-10-e6nz-intrinsic-api-capability/judge.py'),'fixed_remote_judge','exec'),namespace)
    verdict=namespace['judge'](data)
    assert verdict==json.loads((out/'verdict.json').read_text(encoding='utf-8')) and verdict['pass']
    steps=json.loads((out/'steps.json').read_text(encoding='utf-8'))
    assert set(steps)=={'judge','api'} and all(r['status']=='COMPLETED' and r['exit_code']==0 and r['cleanup_ok'] for r in steps.values())
    observed={}
    for name,r in data['cases'].items():
        a=r['arrays']; params=r['params']
        assert len(a['x'])==len(a['y'])==73
        width=max(a['x'])-min(a['x']); height=max(a['y'])-min(a['y'])
        assert abs(width/2e-4-1)<1e-12 and abs(height/.5e-4-1)<1e-12
        ni=params['n_i']; sigma=params['ElectronCharge']*(params['mu_n']+params['mu_p'])*ni
        expected=sigma*height/width*r['voltage']
        source=r['contacts'][1]; actual=r['result_current'][source]
        observed[name]={'actual_A_per_cm':actual,'expected_A_per_cm':expected,
            'max_n_relative_error':max(abs(v/ni-1) for v in a['Electrons']),
            'max_p_relative_error':max(abs(v/ni-1) for v in a['Holes'])}
        assert all(v==0 for v in r['canonical_before']+r['canonical_after'])
    assert observed['positive']['actual_A_per_cm']>0 and observed['negative']['actual_A_per_cm']<0
    assert abs(observed['positive']['actual_A_per_cm']+observed['negative']['actual_A_per_cm'])/abs(observed['positive']['expected_A_per_cm'])<1e-2
    print(json.dumps({'evidence_integrity_pass':True,'pilot_pass':True,'inputs':len(summary['inputs']),
        'raw_files':len(summary['outputs'])+1,'checks':len(verdict['checks']),
        'actual_solves':sum(r['solves'] for r in data['cases'].values()),'observed':observed,'engine_imports':0}))

if __name__=='__main__':
    main(Path(sys.argv[1]))
