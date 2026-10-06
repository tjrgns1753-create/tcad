"""고정된 1D PN 기준 문제. 현재 공정 웨이퍼나 일반 2D PN의 승인 경로가 아니다."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

DATA = Path(__file__).with_name('reference_data')
HASHES = {'pn_1d_arrays.npz':'3fb54277848ab4522cb23bf3fd6755d6a059e56130f1a31932f1617e10fa25b4',
          'pn_1d_record.json':'52bb73beae473188308616e9c4fbcce1e879c6ba25e67924f377c08e1b7d50d5'}
VOLTS = {'control':[.001], 'fwd':[.1,.2,.3,.4,.5,.6], 'rev':[-.25,-.5,-.75,-1.]}
SNAPS = {'control':[.001], 'fwd':[0.,.3,.5,.6], 'rev':[0.,-.5,-1.]}
CONTACTS = ['Si_xmin','Si_xmax']
SCOPE = '고정된 1D 대칭 Si PN 기준 문제 — 현재 공정 웨이퍼의 측정이나 실험 검증이 아님'
SOURCES = ['https://devsim.com/1d-diode-junction-part-ii/',
           'https://doi.org/10.1109/T-ED.1969.16566',
           'https://doi.org/10.1103/PhysRev.87.835',
           'https://ocw.mit.edu/courses/6-012-microelectronic-devices-and-circuits-fall-2009/resources/mit6_012f09_lec04/']


def reference():
    for name,sha in HASHES.items():
        if hashlib.sha256((DATA/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('PN_REFERENCE_HASH_MISMATCH:'+name)
    with np.load(DATA/'pn_1d_arrays.npz',allow_pickle=False) as z:
        arrays={k:z[k].copy() for k in z.files}
    return json.loads((DATA/'pn_1d_record.json').read_text()),arrays


def canonical(control=False):
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe, advance_wafer_state
    # 명시적인 analytic 입력. 빈 path로 공정 mesh가 있다고 주장하지 않는다.
    pr=ProcessResult('',material_regions=[MaterialRegion('Si',0)],metadata={'origin':'ANALYTIC_REFERENCE_NOT_PROCESS'})
    if control:
        doped=apply_uniform_doping(pr,{'Si':1e16},{'Si':0.},chemical_state='ACTIVE')
    else:
        doped=apply_step_junction_doping(pr,'Si','x',0.,1e17,1e17,chemical_state='ACTIVE')
    initial=initial_wafer_state_from_recipe({'x_extent_um':40.,'silicon_depth_um':.1,'grid_delta_um':0.})
    return advance_wafer_state(initial,doped,'doping')


def build_device(dv,name,x):
    mesh=name+'_mesh'
    dv.create_1d_mesh(mesh=mesh)
    for i,pos in enumerate(x):
        tag={'tag':CONTACTS[0]} if i==0 else {'tag':CONTACTS[1]} if i==len(x)-1 else {}
        dv.add_1d_mesh_line(mesh=mesh,pos=float(pos),ps=.004,**tag)
    for c in CONTACTS:
        dv.add_1d_contact(mesh=mesh,name=c,tag=c,material='metal')
    dv.add_1d_region(mesh=mesh,region='Si',material='Si',tag1=CONTACTS[0],tag2=CONTACTS[1])
    dv.finalize_mesh(mesh=mesh)
    dv.create_device(mesh=mesh,device=name)
    actual=np.array(dv.get_node_model_values(device=name,region='Si',name='x'))
    if len(actual)!=1545 or not np.array_equal(np.sort(actual),x):
        raise ValueError('PN_REFERENCE_NATIVE_COORDINATES_CHANGED')


def run_device(dv,kind,x):
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    name='pn_reference_'+kind
    rec={'kind':kind,'error':None,'cleanup_ok':False,'solve_attempts':0,'solves':0,'solve_failures':0,'snapshot_failures':0,'profiles':{}}
    original=dv.solve
    def native(nm):
        return np.array(dv.get_node_model_values(device=name,region='Si',name=nm))
    def observed(*args,**kwargs):
        rec['solve_attempts']+=1
        try:
            value=original(*args,**kwargs)
        except Exception:
            rec['solve_failures']+=1
            raise
        rec['solves']+=1
        try:
            if 'Electrons' in dv.get_node_model_list(device=name,region='Si'):
                v=float(dv.get_parameter(device=name,name=CONTACTS[0]+'_bias'))
                if v in SNAPS[kind]:
                    rec['profiles'][str(v)]={nm:native(nm).tolist() for nm in ('Potential','Electrons','Holes')}
                    rec['profiles'][str(v)]['ElectricField']=list(dv.get_edge_model_values(device=name,region='Si',name='ElectricField'))
        except Exception:
            rec['snapshot_failures']+=1
            raise
        return value
    try:
        build_device(dv,name,x)
        xx,yy=native('x'),native('y')
        state=canonical(kind=='control')
        for a,b in zip(xx,yy):
            q=state.net_doping_at(float(a)*1e4,float(b)*1e4)
            expected=(1e16,0.,1e16) if kind=='control' else (1e17*(a>=0),1e17*(a<=0),1e17*((a>=0)*1-(a<=0)*1))
            if q.physics_status is not None or (q.donor_concentration,q.acceptor_concentration,q.net_doping)!=expected:
                raise ValueError('PN_REFERENCE_CANONICAL_UNSUPPORTED')
        rec['canonical_checked']=len(xx)
        apply_doping(name,'Si',state,length_scale_to_cm=1e-4)
        rec['x_cm']=xx.tolist()
        for nm in ('Donors','Acceptors','NetDoping'):
            rec[nm]=native(nm).tolist()
        dv.solve=observed
        result=run_pn_junction_iv_sweep(name,'Si',CONTACTS,CONTACTS[0],VOLTS[kind],{CONTACTS[1]:0.})
        rec['currents']=[{'V':pt.voltages[CONTACTS[0]],'left':pt.currents[CONTACTS[0]],'right':pt.currents[CONTACTS[1]]} for pt in result.points]
        rec['params']={nm:float(dv.get_parameter(device=name,region='Si',name=nm)) for nm in ('ElectronCharge','n_i','T','mu_n','mu_p','taun','taup','Permittivity','V_t')}
        dv.edge_from_node_model(device=name,region='Si',node_model='x')
        for nm in ('x@n0','x@n1','EdgeLength'):
            rec[nm]=list(dv.get_edge_model_values(device=name,region='Si',name=nm))
    except Exception as exc:
        rec['error']=type(exc).__name__+': '+str(exc)[:500]
    finally:
        dv.solve=original
        try:
            if name in dv.get_device_list():
                dv.delete_device(device=name)
            if name+'_mesh' in dv.get_mesh_list():
                dv.delete_mesh(mesh=name+'_mesh')
            rec['cleanup_ok']=not dv.get_device_list() and not dv.get_mesh_list()
        except Exception as exc:
            rec['error']='CLEANUP_FAILED: '+str(exc)[:300]
    return rec


def validate(devices,baseline,arrays):
    checks=[]
    def need(name,ok,value=None):
        checks.append({'name':name,'pass':bool(ok),'value':value})
    for kind in VOLTS:
        r=devices[kind]
        count=2+len(VOLTS[kind])
        if r['error'] or r['cleanup_ok'] is not True or any(type(r.get(k)) is not int or r[k]!=v for k,v in {'solve_attempts':count,'solves':count,'solve_failures':0,'snapshot_failures':0,'canonical_checked':1545}.items()):
            raise ValueError('PN_REFERENCE_INCOMPLETE:'+kind)
        if r['params']!=baseline['devices'][kind]['params']:
            raise ValueError('PN_REFERENCE_PARAMETERS_CHANGED')
        x=np.asarray(r['x_cm'])
        gx=arrays[kind+'_x']
        if x.shape!=(1545,) or not np.all(np.isfinite(x)) or not np.array_equal(np.sort(x),np.sort(gx)):
            raise ValueError('PN_REFERENCE_GRID_CHANGED')
        for nm in ('Donors','Acceptors','NetDoping'):
            if not np.array_equal(np.asarray(r[nm])[np.argsort(x)],arrays[kind+'_'+nm][np.argsort(gx)]):
                raise ValueError('PN_REFERENCE_DOPING_CHANGED')
        if len(r['currents'])!=len(VOLTS[kind]):
            raise ValueError('PN_REFERENCE_CURRENTS_MISSING')
        for row,g,v in zip(r['currents'],baseline['devices'][kind]['currents'],VOLTS[kind]):
            if row['V']!=v or any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) for k in ('V','left','right')) or row['left']==0:
                raise ValueError('PN_REFERENCE_CURRENT_INVALID')
            kcl=abs(row['left']+row['right'])/abs(row['left'])
            need(kind+'_'+str(v)+'_전류보존',kcl<=(1e-6 if kind=='control' else 1e-3),kcl)
            need(kind+'_'+str(v)+'_기준전류',abs(row['left']-g['I_min'])/abs(g['I_min'])<=.01)
            need(kind+'_'+str(v)+'_전류부호',row['left']*v>0)
        need(kind+'_전류단조성',np.all(np.diff(np.abs([r['left'] for r in r['currents']]))>0))
        order=np.argsort(x)
        go=np.argsort(gx)
        e0,e1,ell=[np.asarray(r[nm]) for nm in ('x@n0','x@n1','EdgeLength')]
        if any(a.shape!=(1544,) for a in (e0,e1,ell)) or np.any(ell<=0) or not np.all(np.isfinite(ell)):
            raise ValueError('PN_REFERENCE_EDGE_INVALID')
        xs=np.sort(x)
        i0,i1=np.searchsorted(xs,e0),np.searchsorted(xs,e1)
        if np.any(i0>=len(xs)) or np.any(i1>=len(xs)) or not np.array_equal(xs[i0],e0) or not np.array_equal(xs[i1],e1):
            raise ValueError('PN_REFERENCE_EDGE_ENDPOINT_CHANGED')
        pairs=np.sort(np.column_stack((e0,e1)),axis=1)
        pairs=pairs[np.argsort(pairs[:,0])]
        if not np.array_equal(pairs,np.column_stack((xs[:-1],xs[1:]))) or not np.allclose(ell,abs(e1-e0),rtol=1e-12,atol=0):
            raise ValueError('PN_REFERENCE_EDGE_TOPOLOGY_CHANGED')
        for v in SNAPS[kind]:
            s=r['profiles'][str(v)]
            for nm in ('Potential','Electrons','Holes'):
                a=np.asarray(s[nm]); g=arrays[f'{kind}_{v}_{nm}']
                if a.shape!=(1545,) or not np.all(np.isfinite(a)) or (nm!='Potential' and np.any(a<=0)):
                    raise ValueError('PN_REFERENCE_PROFILE_INVALID')
                error=float(np.max(abs(a[order]-g[go]))) if nm=='Potential' else float(np.max(abs(a[order]-g[go])/g[go]))
                need(f'{kind}_{v}_{nm}_기준',error<=(.01*r['params']['V_t'] if nm=='Potential' else .01),error)
            field=np.asarray(s['ElectricField'])
            psi=np.asarray(s['Potential'])[order]
            if field.shape!=(1544,) or not np.all(np.isfinite(field)):
                raise ValueError('PN_REFERENCE_FIELD_INVALID')
            need(f'{kind}_{v}_전계일관성',np.allclose(field,(psi[i0]-psi[i1])/ell,rtol=1e-9,atol=1e-7))
    ctl=devices['control']; p=ctl['params']
    n=(1e16+math.sqrt(1e32+4*p['n_i']**2))/2
    theory=p['ElectronCharge']*(p['mu_n']*n+p['mu_p']*p['n_i']**2/n)*.001/.004
    need('저항해석식_단위_A_per_cm2',abs(ctl['currents'][0]['left']-theory)/theory<=1e-6)
    f,r=devices['fwd'],devices['rev']
    order=np.argsort(f['x_cm'])
    psi=np.asarray(f['profiles']['0.0']['Potential'])[order]
    vbi=f['params']['V_t']*math.log(1e34/f['params']['n_i']**2)
    need('문헌_내장전위',abs((psi[-1]-psi[0])-vbi)<=.01*f['params']['V_t'],{'computed_V':float(psi[-1]-psi[0]),'analytic_V':vbi})
    e_eq=max(abs(np.asarray(f['profiles']['0.0']['ElectricField'])))
    need('순방향_장벽완화',np.ptp(f['profiles']['0.6']['Potential'])<np.ptp(f['profiles']['0.0']['Potential']))
    need('역방향_장벽증가',np.ptp(r['profiles']['-1.0']['Potential'])>np.ptp(r['profiles']['0.0']['Potential']))
    need('순방향_전계완화',max(abs(np.asarray(f['profiles']['0.6']['ElectricField'])))<e_eq)
    need('역방향_전계증가',max(abs(np.asarray(r['profiles']['-1.0']['ElectricField'])))>e_eq)
    return checks


def run(out):
    baseline,arrays=reference()  # 엔진 import 전에 입력 무결성 검사.
    from tcad.device.devsim import backend
    dv=backend.require_devsim()
    if dv.get_device_list() or dv.get_mesh_list():
        raise RuntimeError('PN_REFERENCE_REQUIRES_EMPTY_ENGINE')
    x=np.sort(arrays['fwd_x'])
    devices={}
    for kind in VOLTS:
        devices[kind]=run_device(dv,kind,x)
        if devices[kind]['error'] or not devices[kind]['cleanup_ok']:
            break
    problems=[]; checks=[]
    try:
        checks=validate(devices,baseline,arrays)
    except Exception as exc:
        problems.append(type(exc).__name__+': '+str(exc))
    passed=bool(checks) and not problems and all(c['pass'] for c in checks)
    result={'schema':1,'status':'REFERENCE_MODEL_CHECKS_PASS' if passed else 'REFERENCE_MODEL_CHECKS_FAILED',
            'scope':SCOPE,'current_unit':'A/cm^2','checks':checks,'problems':problems,'devices':devices,
            'references':SOURCES,'production_2d_gate_released':False}
    Path(out).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return 0 if passed else 1


if __name__=='__main__':
    try:
        raise SystemExit(run(sys.argv[1]))
    except Exception as exc:
        Path(sys.argv[1]).write_text(json.dumps({'schema':1,'status':'REFERENCE_MODEL_CHECKS_FAILED','scope':SCOPE,'checks':[],
                                              'problems':[type(exc).__name__+': '+str(exc)],'production_2d_gate_released':False},ensure_ascii=False),encoding='utf-8')
        raise SystemExit(1)
