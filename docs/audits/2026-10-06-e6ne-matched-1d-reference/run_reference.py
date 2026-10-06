"""공식 API와 기존 production 물리 경로의 동일 x격자 1D 참조."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

import common as C


def build_device(dv,name,x):
    mesh = name+'_mesh'
    dv.create_1d_mesh(mesh=mesh)
    for k,xx in enumerate(x):
        kw = {'tag':C.P.T.C_MIN} if k==0 else {'tag':C.P.T.C_MAX} if k==len(x)-1 else {}
        dv.add_1d_mesh_line(mesh=mesh,pos=float(xx),ps=float(x[-1]-x[0]),**kw)
    for cn in (C.P.T.C_MIN,C.P.T.C_MAX):
        dv.add_1d_contact(mesh=mesh,name=cn,tag=cn,material='metal')
    dv.add_1d_region(mesh=mesh,material='Si',region='Si',tag1=C.P.T.C_MIN,tag2=C.P.T.C_MAX)
    dv.finalize_mesh(mesh=mesh)
    dv.create_device(mesh=mesh,device=name)
    actual = np.array(dv.get_node_model_values(device=name,region='Si',name='x'))
    if len(actual)!=len(x) or len(np.unique(actual))!=len(x) or not np.array_equal(np.sort(actual),x):
        raise ValueError('OFFICIAL_1D_MESH_NOT_EXACT_SOURCE_GRID')
    return mesh


def canonical_audit(state,x,y,kind):
    rec = dict(canonical_checked=0,canonical_unresolved=0,canonical_mismatch=0)
    if len(x)!=len(y):
        raise ValueError('CANONICAL_COORDINATE_LENGTH')
    for xx,yy in zip(x,y):
        q = state.net_doping_at(float(xx)/1e-4,float(yy)/1e-4)
        rec['canonical_checked'] += 1
        values = (q.donor_concentration,q.acceptor_concentration,q.net_doping)
        expected = (1e16,0.,1e16) if kind=='control' else (1e17*(xx>=0),1e17*(xx<=0),1e17*((xx>=0)*1-(xx<=0)*1))
        if q.physics_status is not None or any(v is None or not np.isfinite(v) for v in values):
            rec['canonical_unresolved'] += 1
        elif values!=expected:
            rec['canonical_mismatch'] += 1
    C.P.M.require_canonical(rec,len(x))
    return rec


def run_device(dv,state,kind,x,arrays,raw):
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from run_e6na import cleanup
    name = 'e6ne_'+kind
    rec = {'error':None,'cleanup_ok':False,'kind':kind}
    raw['devices'][kind] = rec
    obs = None
    mesh = name+'_mesh'
    try:
        build_device(dv,name,x)
        native = lambda nm:np.array(dv.get_node_model_values(device=name,region='Si',name=nm))
        xx,yy = native('x'),native('y')
        rec.update(nodes=len(xx),dimension=int(dv.get_dimension(device=name)))
        rec['canonical_audit'] = canonical_audit(state,xx,yy,kind)
        obs = C.P.T.Obs(dv,name)
        obs.install()
        apply_doping(name,'Si',state,length_scale_to_cm=1e-4)
        rec['doping_writes_before_solve'] = [list(w) for w in obs.writes]
        volts = [.001] if kind=='control' else C.P.M.VOLTAGES[kind]
        result = run_pn_junction_iv_sweep(device=name,region='Si',all_contacts=[C.P.T.C_MIN,C.P.T.C_MAX],sweep_contact=C.P.T.C_MIN,sweep_voltages=volts,fixed_contacts={C.P.T.C_MAX:0.})
        rec['metadata'] = dict(result.metadata)
        rec['params'] = {nm:float(dv.get_parameter(device=name,region='Si',name=nm)) for nm in C.P.T.J.PARAMS+('V_t',)}
        rec['currents'] = [{'V':v,'I_min':float(pt.currents[C.P.T.C_MIN]),'I_max':float(pt.currents[C.P.T.C_MAX])} for v,pt in zip(volts,result.points)]
        for nm in ('x','y','NodeVolume','Donors','Acceptors','NetDoping'):
            arrays[kind+'_'+nm] = native(nm)
        dv.edge_from_node_model(device=name,region='Si',node_model='x')
        for nm in ('x@n0','x@n1','EdgeLength'):
            arrays[kind+'_'+nm] = np.array(dv.get_edge_model_values(device=name,region='Si',name=nm))
        needed = [.001] if kind=='control' else C.P.M.SNAP_BIASES[kind]
        for v in needed:
            hit = [s for s in obs.snaps if s['has_DD'] and abs(s['bias_min']-v)<1e-12 and s['bias_max']==0]
            if not hit:
                raise ValueError('SNAPSHOT_MISSING')
            for nm in C.P.M.SNAP_ARRAYS:
                arrays[f'{kind}_{v}_{nm}'] = hit[-1][nm]
    except Exception as exc:
        rec['error'] = type(exc).__name__+': '+str(exc).replace(str(C.ROOT),'<REPO>')[:700]
    finally:
        if obs is not None:
            rec.update(solve_attempts=obs.solve_attempts,solves=obs.solves,solve_failures=obs.solve_failures,snapshot_failures=obs.snapshot_failures)
            obs.restore()
        cleanup(dv,name,mesh,rec)
    return rec


def worker(out):
    C.preflight()  # backend import 및 mesh 생성 이전 경계.
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    from tcad.device.devsim import backend
    from run_e6na import require_inputs
    from matched_judge import unit_control
    require_inputs()
    dv = backend.require_devsim()
    if dv.get_device_list() or dv.get_mesh_list():
        raise RuntimeError('ENGINE_NOT_EMPTY')
    with np.load(C.DATA/'arrays.npz',allow_pickle=False) as source:
        x = C.unique_source_x(source)
        state,_ = C.P.T.canonical(C.P.T.write_mesh(source['points_um'],source['triangles'],'matched_state'))
    spec = importlib.util.spec_from_file_location('e6k_original',C.ROOT/'tests/integration/test_pn_1d_diagnostic_real.py')
    one = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(one)
    control_state = one.canonical('res',20.,'matched_control')
    raw = {'plan_sha256':C.PLAN_SHA,'source_hashes':C.INPUT_SHA,'devices':{},'new_2d_solves':0,'production_gate_released':False}
    arrays = {}
    out.mkdir(parents=True,exist_ok=True)
    def persist():
        C.save(out/'record.json',raw)
        np.savez_compressed(out/'arrays.npz',**arrays)
    control = run_device(dv,control_state,'control',x,arrays,raw)
    persist()
    try:
        result = unit_control(control,arrays,x)
        raw['unit_control'] = result
        persist()
        if not result['pass']:
            return 1
    except Exception as exc:
        raw['unit_error'] = str(exc)
        persist()
        return 1
    for direction in C.P.M.DIRECTIONS:
        dr = run_device(dv,state,direction,x,arrays,raw)
        persist()
        if dr['error'] or not dr['cleanup_ok']:
            return 1
    return 0


def main():
    C.preflight()
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        return worker(Path(sys.argv[2]))
    from resource_supervisor import supervise
    from matched_judge import judge
    out = C.ROOT/'e6ne_out'
    out.mkdir(exist_ok=True)
    execution = supervise([sys.executable,'-B',str(__file__),'--worker',str(out/'reference')],C.ROOT,out/'reference.log',candidate_s=300)
    execution['plan_sha256'] = C.PLAN_SHA
    C.save(out/'execution.json',execution)
    result = judge(out)
    C.save(out/'result.json',result)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='MATCHED_REFERENCE_PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
