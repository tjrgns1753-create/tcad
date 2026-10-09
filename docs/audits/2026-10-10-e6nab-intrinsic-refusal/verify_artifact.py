"""원격 origin/배열/실패 주입 출처를 engine 없이 독립 확인한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
SHA='adb174994d72abf3f6cb9d1a1b857dac2cea7e58'
RUN='37984357015'
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
def blob(path):
    return subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'show',SHA+':'+path],cwd=ROOT,
        env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1'))
def analytic(fields,result,params,axis,voltage,side):
    xy=fields['xy_um']; n=len(xy); ax=0 if axis=='x' else 1
    assert n==73 and all(len(fields[k])==n for k in ('potential','electron','hole'))
    coords=[p[ax] for p in xy]; other=[p[1-ax] for p in xy]
    lo,hi=min(coords),max(coords); length=hi-lo; width=max(other)-min(other)
    assert abs(length/(2. if ax==0 else .5)-1)<1e-12
    assert abs(width/(.5 if ax==0 else 2.)-1)<1e-12
    q,ni,mun,mup=(params[k] for k in ('ElectronCharge','n_i','mu_n','mu_p'))
    assert q==1.6e-19 and ni==1e10 and mun==400. and mup==200.
    assert len(result['points'])==1 and result['region']==fields['region']=='Si'
    assert result['metadata']['current_unit']=='A/cm'
    p=result['points'][0]; source=result['sweep_contact']; ground=next(k for k in p['currents'] if k!=source)
    assert p['voltages']=={source:voltage,ground:0.} and len(p['currents'])==2
    g=q*(mun+mup)*ni*width/length;scale=g*length*1e-4*5.;expected=g*voltage
    actual=p['currents'][source]
    metrics={'current_relative_error':abs(actual-expected)/(abs(expected) if voltage else scale),
        'kcl_error':abs(actual+p['currents'][ground])/scale,
        'electron_relative_error':max(abs(z/ni-1) for z in fields['electron']),
        'hole_relative_error':max(abs(z/ni-1) for z in fields['hole'])}
    reference=lo if side=='max' else hi; target=hi if side=='max' else lo
    p0=fields['potential'][coords.index(reference)]
    metrics['potential_linearity_error']=max(abs(phi-(p0+voltage*(x-reference)/(target-reference)))
        for x,phi in zip(coords,fields['potential']))/max(abs(voltage),length*1e-4*5.)
    assert all(math.isfinite(z) and z<=t for z,t in zip(metrics.values(),(1e-2 if voltage else 1e-4,1e-6,1e-4,1e-4,1e-2)))
    return {'actual_A_per_cm':actual,'expected_A_per_cm':expected,'metrics':metrics}
def main(raw):
    summary=json.loads((raw/'summary.json').read_text(encoding='utf-8'))
    assert summary['source']['github_sha']==summary['source']['git_head']==SHA
    assert summary['source']['run_id']==RUN and summary['runner']['runner_environment']=='github-hosted'
    assert summary['status']=='PASS' and summary['exit_code']==0 and not summary['omitted_outputs']
    for r in summary['inputs']:
        b=blob(r['path']);lf=b.replace(b'\r\n',b'\n')
        assert any(len(v)==r['bytes'] and hashlib.sha256(v).hexdigest()==r['sha256'] for v in (b,lf,lf.replace(b'\n',b'\r\n'))),r['path']
    for r in summary['outputs']+[summary['log']]:
        p=raw/('outputs/'+r['path'] if 'path' in r else r['file']);b=p.read_bytes()
        assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    out=raw/'outputs/e6nab_out';data=json.loads((out/'records.json').read_text(encoding='utf-8'))
    plan=blob('docs/audits/2026-10-10-e6nab-intrinsic-refusal/PLAN.md').replace(b'\r\n',b'\n')
    assert hashlib.sha256(plan).hexdigest()==data['plan_sha']
    steps=json.loads((out/'steps.json').read_text(encoding='utf-8'))
    assert set(steps)=={'status','contract','missing','bias','baseline_gui','refusal_gui'}
    assert all(r['status']=='COMPLETED' and r['exit_code']==0 and r['cleanup_ok'] for r in steps.values())
    cases={'x_min_positive':('x',.001),'x_min_negative':('x',-.001),'y_min_negative':('y',-.00025)}
    assert set(data['supported'])==set(cases);observed={}
    for name,(axis,v) in cases.items():
        r=data['supported'][name]
        assert r['axis']==axis and r['voltage']==v and r['side']=='min' and r['solves']==3
        assert r['history_delta']==1 and r['export_equal'] and not r['devices_after'] and not r['meshes_after']
        export=json.loads((out/(name+'_fields.json')).read_text(encoding='utf-8'))
        assert export['snapshot']==r['snapshot'] and export['measurement']['currents']==r['measurement']['points'][0]['currents']
        observed[name]=analytic(r['snapshot'],r['measurement'],r['params'],axis,v,'min')
    faults={'electron_zero','potential_flat','geometry_shift','capture_unavailable','current_doubled','high_field'}
    assert set(data['faults'])==faults
    for name,r in data['faults'].items():
        assert r['state_identity'] and r['history_delta']==0 and r['field_result_none'] and r['success_log_absent']
        assert not r['devices_after'] and not r['meshes_after'] and r['status']['resolution']=='UNSUPPORTED_BY_MODEL'
        if name=='high_field':
            assert r['solves']==r['writes']==r['captures']==0 and not r['original_api_evidence']
            assert r['kind']=='PREFLIGHT' and r['status']['reason_code']=='INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED'
        else:
            assert r['kind']=='AUDIT_FAULT_INJECTION' and r['solves']==3 and r['captures']==1 and r['writes']>0
            assert r['status']['reason_code']=='INTRINSIC_RESULT_NOT_VALIDATED'
            live=r['original_api_evidence']
            analytic(live['original_fields'],live['original_result'],live['params'],'x',.001,'max')
    baseline=json.loads((raw/'outputs/e6naa_out/records.json').read_text(encoding='utf-8'))
    assert len(baseline['cases'])==5 and len(baseline['blocked'])==4
    assert all(r['solves']==3 and r['history_delta']==1 and r['export_equal'] for r in baseline['cases'].values())
    assert all(r['solves']==r['writes']==r['captures']==r['history_delta']==0 for r in baseline['blocked'].values())
    print(json.dumps({'evidence_integrity_pass':True,'inputs':len(summary['inputs']),'raw_files':len(summary['outputs'])+1,
        'supported_new_cases':3,'fault_injections':5,'preflight_refusal':1,'baseline_cases':5,
        'new_actual_solves':24,'baseline_actual_solves':15,'observed':observed,'engine_imports':0}))
if __name__=='__main__':main(Path(sys.argv[1]))
