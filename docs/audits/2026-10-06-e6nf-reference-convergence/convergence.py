"""기존 공식 1D 실행기의 재사용 및 정확한 nested-grid 비교."""
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = ROOT/'docs/audits/2026-10-06-e6ne-matched-1d-reference'
sys.path.insert(0, str(PREVIOUS))
import common as C
import run_reference as R
import matched_judge as J

PLAN_SHA = '352a71f1cd042968b370a455bd9b163300b1feeceb62f7c617ddc21ad2567051'
DATA = PREVIOUS/'raw/outputs/e6ne_out/reference'
INPUT_SHA = {'arrays.npz':'3fb54277848ab4522cb23bf3fd6755d6a059e56130f1a31932f1617e10fa25b4',
             'record.json':'52bb73beae473188308616e9c4fbcce1e879c6ba25e67924f377c08e1b7d50d5'}


def preflight(callback=None):
    C.preflight()
    if hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    for name, sha in INPUT_SHA.items():
        if hashlib.sha256((DATA/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('REFERENCE_HASH_MISMATCH:'+name)
    return callback() if callback else PLAN_SHA


def refine(x):
    x = np.asarray(x)
    if x.shape!=(1545,) or not np.all(np.isfinite(x)) or np.any(np.diff(x)<=0):
        raise ValueError('COARSE_GRID_INVALID')
    fine = np.empty(3089)
    fine[::2], fine[1::2] = x, x[:-1]+np.diff(x)/2
    if np.any(np.diff(fine)<=0) or not np.array_equal(fine[::2],x):
        raise ValueError('NESTED_GRID_INVALID')
    return fine


def compare(raw, fine, coarse_raw, coarse):
    if raw.get('plan_sha256')!=PLAN_SHA or raw.get('source_hashes')!=INPUT_SHA:
        raise ValueError('IDENTITY_MISMATCH')
    checks, metrics = [], {}
    for d in C.P.M.DIRECTIONS:
        old, new = coarse_raw['devices'][d], raw['devices'][d]
        xold = J.arr(coarse,d+'_x',1545)
        xfine = J.arr(fine,d+'_x',3089)
        xsort = np.sort(xold)
        if not np.array_equal(np.sort(xfine),refine(xsort)):
            raise ValueError('FINE_GRID_CHANGED')
        mapping = C.matched_indices(np.sort(xfine),xold)
        order = np.argsort(xfine)
        C.P.M.require_canonical(new['canonical_audit'],3089)
        if new.get('error') is not None or new.get('cleanup_ok') is not True:
            raise ValueError('DEVICE_ERROR_OR_CLEANUP')
        for name, expected in {'nodes':3089,'dimension':1,'solve_attempts':2+len(C.P.M.VOLTAGES[d]),'solves':2+len(C.P.M.VOLTAGES[d]),'solve_failures':0,'snapshot_failures':0}.items():
            if type(new.get(name)) is not int or new[name]!=expected:
                raise ValueError('COUNTER_MISMATCH:'+name)
        if new['params']!=old['params'] or new['metadata']!=old['metadata'] or new['doping_writes_before_solve']!=old['doping_writes_before_solve']:
            raise ValueError('PRODUCTION_CONTRACT_CHANGED')
        if not np.all(J.arr(fine,d+'_y',3089)==0):
            raise ValueError('NOT_1D')
        for name, expected in [('Donors',1e17*(xfine>=0)),('Acceptors',1e17*(xfine<=0)),('NetDoping',1e17*((xfine>=0)*1-(xfine<=0)*1))]:
            if not np.array_equal(J.arr(fine,d+'_'+name,3089),expected):
                raise ValueError('DOPING_MISMATCH')
        volumes=J.arr(fine,d+'_NodeVolume',3089)
        if np.any(volumes<0) or abs(float(np.sum(volumes))/.004-1)>1e-12:
            raise ValueError('VOLUME_MISMATCH')
        e0,e1,ell=[J.arr(fine,d+'_'+nm,3088) for nm in ('x@n0','x@n1','EdgeLength')]
        pairs=np.sort(np.column_stack((e0,e1)),axis=1)
        pairs=pairs[np.argsort(pairs[:,0])]
        xs=np.sort(xfine)
        if not np.array_equal(pairs,np.column_stack((xs[:-1],xs[1:]))) or np.any(ell<=0) or not np.allclose(ell,abs(e1-e0),rtol=1e-12,atol=0):
            raise ValueError('EDGE_TOPOLOGY_MISMATCH')
        if len(new['currents'])!=len(C.P.M.VOLTAGES[d]):
            raise ValueError('CURRENTS_INCOMPLETE')
        currents=[]
        for a,b,v in zip(old['currents'],new['currents'],C.P.M.VOLTAGES[d]):
            if not all(J.number(b.get(k)) for k in ('V','I_min','I_max')) or b['V']!=v or b['I_min']==0:
                raise ValueError('CURRENT_INVALID')
            rel=abs(a['I_min']-b['I_min'])/abs(b['I_min'])
            kcl=abs(b['I_min']+b['I_max'])/abs(b['I_min'])
            checks.append({'name':f'{d}_current_{v}','pass':bool(rel<=(.01 if d=='fwd' else .02) and kcl<=1e-3 and b['I_min']*v>0)})
            currents.append({'V':v,'relative':rel,'kcl_relative':kcl,'fine_J_A_per_cm2':b['I_min']})
        checks.append({'name':d+'_monotonic','pass':bool(np.all(np.diff(np.abs([c['I_min'] for c in new['currents']]))>0))})
        oe0,oe1,oell=[J.arr(coarse,d+'_'+nm,1544) for nm in ('x@n0','x@n1','EdgeLength')]
        i0,i1=C.matched_indices(xsort,oe0),C.matched_indices(xsort,oe1)
        old_order=np.argsort(xold)
        profiles=[]
        for v in C.P.M.SNAP_BIASES[d]:
            values={nm:J.arr(fine,f'{d}_{v}_{nm}',3089,positive=nm in ('Electrons','Holes'))[order][mapping] for nm in ('Potential','Electrons','Holes')}
            old_values={nm:J.arr(coarse,f'{d}_{v}_{nm}',1545,positive=nm in ('Electrons','Holes')) for nm in values}
            psi=float(np.max(abs(values['Potential']-old_values['Potential'])))
            carrier={nm:float(np.max(abs(values[nm]-old_values[nm])/values[nm])) for nm in ('Electrons','Holes')}
            ep=(values['Potential'][old_order][i0]-values['Potential'][old_order][i1])/oell
            eo=(old_values['Potential'][old_order][i0]-old_values['Potential'][old_order][i1])/oell
            field=float(np.max(abs(ep-eo))/np.max(abs(ep)))
            native=J.arr(fine,f'{d}_{v}_ElectricField',3088)
            allpsi=J.arr(fine,f'{d}_{v}_Potential',3089)[order]
            f0,f1=C.matched_indices(xs,e0),C.matched_indices(xs,e1)
            if not np.allclose(native,(allpsi[f0]-allpsi[f1])/ell,rtol=1e-9,atol=1e-7):
                raise ValueError('NATIVE_FIELD_MISMATCH')
            checks.append({'name':f'{d}_profile_{v}','pass':bool(psi<=.01*new['params']['V_t'] and max(carrier.values())<=.01 and field<=.02)})
            profiles.append({'V':v,'potential_max_V':psi,'carriers_relative':carrier,'field_peak_normalized':field})
        metrics[d]={'currents':currents,'profiles':profiles}
    return checks,metrics


def judge(out):
    problems, checks, metrics=[],[],{}
    try:
        preflight()
        ex=json.loads((out/'execution.json').read_text())
        if ex['plan_sha256']!=PLAN_SHA or ex['status']!='COMPLETED' or ex['cleanup_ok'] is not True or type(ex['exit_code']) is not int or ex['exit_code']!=0:
            raise ValueError('EXECUTION_INCOMPLETE')
        raw=json.loads((out/'reference/record.json').read_text())
        old=json.loads((DATA/'record.json').read_text())
        with np.load(out/'reference/arrays.npz',allow_pickle=False) as fine, np.load(DATA/'arrays.npz',allow_pickle=False) as coarse:
            checks,metrics=compare(raw,fine,old,coarse)
    except Exception as exc:
        problems.append(type(exc).__name__+': '+str(exc))
    passed=bool(checks) and len(checks)==19 and not problems and all(c['pass'] is True for c in checks)
    return {'status':'REFERENCE_CONVERGENCE_PASS' if passed else 'REFERENCE_CONVERGENCE_NOT_APPROVED','checks':checks,'metrics':metrics,'problems':problems,'production_gate_released':False,'new_2d_solves':0}


def worker(out):
    preflight()
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    from tcad.device.devsim import backend
    from run_e6na import require_inputs
    require_inputs()
    dv=backend.require_devsim()
    if dv.get_device_list() or dv.get_mesh_list():
        raise RuntimeError('ENGINE_NOT_EMPTY')
    with np.load(C.DATA/'arrays.npz',allow_pickle=False) as source:
        state,_=C.P.T.canonical(C.P.T.write_mesh(source['points_um'],source['triangles'],'convergence_state'))
    with np.load(DATA/'arrays.npz',allow_pickle=False) as old:
        x=refine(np.sort(old['fwd_x']))
    raw={'plan_sha256':PLAN_SHA,'source_hashes':INPUT_SHA,'devices':{}}
    arrays={}
    out.mkdir(parents=True,exist_ok=True)
    for direction in C.P.M.DIRECTIONS:
        dr=R.run_device(dv,state,direction,x,arrays,raw)
        C.save(out/'record.json',raw)
        np.savez_compressed(out/'arrays.npz',**arrays)
        if dr['error'] or not dr['cleanup_ok']:
            return 1
    return 0


def main():
    preflight()
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        return worker(Path(sys.argv[2]))
    from resource_supervisor import supervise
    out=ROOT/'e6nf_out'
    out.mkdir(exist_ok=True)
    ex=supervise([sys.executable,'-B',str(__file__),'--worker',str(out/'reference')],ROOT,out/'reference.log',candidate_s=120)
    ex['plan_sha256']=PLAN_SHA
    C.save(out/'execution.json',ex)
    result=judge(out)
    C.save(out/'result.json',result)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='REFERENCE_CONVERGENCE_PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
