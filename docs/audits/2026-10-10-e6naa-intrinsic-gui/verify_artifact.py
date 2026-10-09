"""전체 배열·해석 전류·원격 출처를 엔진 없이 독립 검증한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
SHA='ad59b772cc9b1fb157816808306231e806bf4a29'
RUN='37983547425'
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
    for r in summary['inputs']:
        b=blob(r['path']); lf=b.replace(b'\r\n',b'\n')
        assert any(len(v)==r['bytes'] and hashlib.sha256(v).hexdigest()==r['sha256'] for v in (b,lf,lf.replace(b'\n',b'\r\n'))),r['path']
    for r in summary['outputs']+[summary['log']]:
        p=raw/('outputs/'+r['path'] if 'path' in r else r['file']); b=p.read_bytes()
        assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    out=raw/'outputs/e6naa_out'; data=json.loads((out/'records.json').read_text(encoding='utf-8'))
    plan=blob('docs/audits/2026-10-10-e6naa-intrinsic-gui/PLAN.md').replace(b'\r\n',b'\n')
    assert hashlib.sha256(plan).hexdigest()==data['plan_sha']
    steps=json.loads((out/'steps.json').read_text(encoding='utf-8'))
    assert set(steps)=={'contract','missing','bias','gui','canonical'}
    assert all(r['status']=='COMPLETED' and r['exit_code']==0 and r['cleanup_ok'] for r in steps.values())
    cases={'x_zero':('x',0.),'x_positive':('x',.001),'x_negative':('x',-.001),'y_positive':('y',.00025),'fresh_gui':('x',.001)}
    assert set(data['cases'])==set(cases)
    observed={}
    for name,(axis,v) in cases.items():
        r=data['cases'][name]; fields=r['snapshot']; result=r['measurement']; params=r['params']; point=result['points'][0]
        assert r['axis']==axis and r['voltage']==v and r['solves']==3 and r['captures']==1
        assert r['history_delta']==1 and r['attachments']==0 and not r['devices_after'] and not r['meshes_after']
        assert r['export_equal'] and r['live_api_equal']
        xy=fields['xy_um']; n=len(xy)
        assert n>0 and (name=='fresh_gui' or n==73)
        for field in ('potential','electron','hole'):
            assert len(fields[field])==n and all(math.isfinite(z) for z in fields[field])
        for a in r['doping'].values(): assert len(a)==n and all(z==0 for z in a)
        assert set(r['doping'])=={'Donors','Acceptors','NetDoping'}
        assert set(r['rendered'])=={'potential','electron','hole'}
        assert all(z['nodes']==n for z in r['rendered'].values())
        export=json.loads((out/(name+'_fields.json')).read_text(encoding='utf-8'))
        assert export['snapshot']==fields and export['measurement']['currents']==point['currents'] and export['measurement']['voltages']==point['voltages']
        assert result['metadata']['device_input']=='CANONICAL_KNOWN_UNDOPED' and result['metadata']['current_unit']=='A/cm'
        assert params['n_i']==1e10 and params['T']==300. and params['mu_n']==400. and params['mu_p']==200.
        assert params['taun']==params['taup']==1e-8
        ax=0 if axis=='x' else 1
        coordinates=[p[ax] for p in xy]; other=[p[1-ax] for p in xy]
        lo,hi=min(coordinates),max(coordinates); length=hi-lo; width=max(other)-min(other)
        assert abs(length/(2. if axis=='x' else .5)-1)<1e-6
        assert abs(width/(.5 if axis=='x' else 2.)-1)<1e-6
        g=params['ElectronCharge']*(params['mu_n']+params['mu_p'])*params['n_i']*width/length
        source=result['sweep_contact']; currents=point['currents']; ground=next(k for k in currents if k!=source)
        assert len(currents)==len(point['voltages'])==2 and point['voltages']=={source:v,ground:0.}
        actual=currents[source]; expected=g*v; scale=g*length*1e-4*5.
        err=abs(actual-expected)/(abs(expected) if v else scale)
        kcl=abs(actual+currents[ground])/scale
        ne=max(abs(z/params['n_i']-1) for z in fields['electron'])
        pe=max(abs(z/params['n_i']-1) for z in fields['hole'])
        p0=fields['potential'][coordinates.index(lo)]
        phi=max(abs(p-(p0+v*(x-lo)/length)) for x,p in zip(coordinates,fields['potential']))/max(abs(v),length*1e-4*5.)
        metrics={'current_relative_error':err,'kcl_error':kcl,'electron_relative_error':ne,'hole_relative_error':pe,'potential_linearity_error':phi}
        assert all(z<=tol for z,tol in zip(metrics.values(),(1e-2 if v else 1e-4,1e-6,1e-4,1e-4,1e-2)))
        recorded=result['metadata']['intrinsic_analytic_validation']
        assert set(recorded)==set(metrics)
        assert all(abs(recorded[k]-z)<1e-10 for k,z in metrics.items())
        observed[name]={'nodes':n,'actual_A_per_cm':actual,'expected_A_per_cm':expected,'metrics':metrics}
    assert set(data['blocked'])=={'high_field','unresolved','chemical','active_missing_profile'}
    for r in data['blocked'].values():
        assert r=={'solves':0,'writes':0,'captures':0,'history_delta':0,'fields_none':True,'state_identity':True}
    print(json.dumps({'evidence_integrity_pass':True,'inputs':len(summary['inputs']),'raw_files':len(summary['outputs'])+1,
        'supported_gui_cases':5,'refusals':4,'actual_gui_solves':15,'observed':observed,'engine_imports':0}))
if __name__=='__main__': main(Path(sys.argv[1]))
