"""고정 계획의 전이 메쉬 PN 파일럿. Production 물리/게이트는 수정하지 않는다."""
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN_SHA = 'a11d5440fdfaf4e2e0e58be464a62080f08e08831427e611677338f69c22768d'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'docs/audits/2026-10-02-e6na-import-reduction'))
spec = importlib.util.spec_from_file_location('pn_existing', ROOT/'tests/integration/test_pn_2d_1d_consistency_real.py')
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
M = T.M


def require_plan():
    sha = hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    if sha != PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH')
    return sha


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def worker(level, out):
    require_plan()  # 엔진 준비/메쉬 생성보다 먼저 실행한다.
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.name != 'nt':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    from tcad.device.devsim import backend, mesh_refine as R
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from conformity_e6h import check_conformity
    from run_e6na import cleanup, require_inputs
    require_inputs()
    dv = backend.require_devsim()
    if dv.get_device_list() or dv.get_mesh_list():
        raise RuntimeError('NONEMPTY_ENGINE')
    refs = np.load(T.E6K/'states.npz', allow_pickle=False)
    lv, ny, expected = [('L0',16,(8037,15264)), ('L1',32,(31173,60736))][level]
    with patch.object(M, 'Y_LINES_UM', np.linspace(-M.H_UM,0,ny+1).tolist()):
        p, t = M.build_mesh(M.e6k_snapshot(refs,lv,'rev',0)['x'])
    p,t,tags,_ = R.structured_lateral_refine(p,t,np.zeros(len(t),dtype=int),[0.],[.1])
    g, c = M.geometry_checks(p,t), check_conformity(p,t)
    if (len(p),len(t)) != expected or not c['pass'] or g['obtuse_triangles'] or g['degenerate_triangles'] or g['area_rel_err']>1e-12:
        raise RuntimeError('GEOMETRY_BLOCKED')
    state, doped = T.canonical(T.write_mesh(p,t,lv))
    rec = {'level':lv,'plan_sha256':PLAN_SHA,'geometry':g,'conformity':c,'devices':{}}
    arr = {'points_um':p,'triangles':t}
    out.mkdir(parents=True,exist_ok=True)
    for direction in M.DIRECTIONS:
        name = f'e6nd_{lv}_{direction}'
        mesh = name+'_mesh'
        dr = {'error':None, 'cleanup_ok':False}
        rec['devices'][direction] = dr
        obs = None
        try:
            imp = import_process_result(doped,mesh_name=mesh,device_name=name,contact_regions=['Si'],contact_axis='x',length_scale_to_cm=T.LENGTH_SCALE)
            x = np.array(dv.get_node_model_values(device=name,region='Si',name='x'))
            y = np.array(dv.get_node_model_values(device=name,region='Si',name='y'))
            dr['node_count'] = len(x)
            dr['area_gate'] = imp.area_conservation['Si']
            if not dr['area_gate']['pass'] or list(imp.regions)!=['Si']:
                raise RuntimeError('IMPORT_AREA_BLOCKED')
            dr['contacts'] = {}
            for cn, xx in [(T.C_MIN,-.002),(T.C_MAX,.002)]:
                idx = T.nodes_of_contact(dv,name,cn)
                if not idx or not np.all(x[idx]==xx) or min(y[idx])!=-M.H_CM or max(y[idx])!=0:
                    raise RuntimeError('CONTACT_BLOCKED')
                dr['contacts'][cn] = idx
            gate = T.Obs(dv,name)
            gate.install()
            try:
                apply_doping(name,'Si',state,length_scale_to_cm=T.LENGTH_SCALE)
                raise RuntimeError('PRODUCTION_GATE_NOT_RAISED')
            except UnsupportedDopingState as exc:
                dr['gate'] = dict(exc.physics_status or {})
            finally:
                gate.restore()
                dr['gate_counts'] = {'writes':len(gate.writes),'attempts':gate.solve_attempts}
            if dr['gate'].get('reason_code')!=T.J.GATE_REASON or gate.writes or gate.solve_attempts:
                raise RuntimeError('GATE_CONTRACT_BLOCKED')
            dr['canonical_audit'] = M.canonical_checks(state,x,y,T.LENGTH_SCALE)
            M.require_canonical(dr['canonical_audit'],len(x))
            obs = T.Obs(dv,name)
            obs.install()
            for nm, vals in [('Donors',M.N_DOP*(x>=0)),('Acceptors',M.N_DOP*(x<=0)),('NetDoping',M.N_DOP*((x>=0)*1-(x<=0)*1))]:
                dv.node_model(device=name,region='Si',name=nm,equation='0')
                dv.set_node_values(device=name,region='Si',name=nm,values=vals.tolist())
            sweep = run_pn_junction_iv_sweep(device=name,region='Si',all_contacts=imp.contacts,sweep_contact=T.C_MIN,sweep_voltages=M.VOLTAGES[direction],fixed_contacts={T.C_MAX:0.})
            dr['metadata'] = dict(sweep.metadata)
            dr['params'] = {n:float(dv.get_parameter(device=name,region='Si',name=n)) for n in T.J.PARAMS+('V_t',)}
            dr['currents'] = [{'V':v,'I_min':float(pt.currents[T.C_MIN]),'I_max':float(pt.currents[T.C_MAX])} for v,pt in zip(M.VOLTAGES[direction],sweep.points)]
            dv.edge_from_node_model(device=name,region='Si',node_model='x')
            dv.edge_from_node_model(device=name,region='Si',node_model='y')
            arr[direction+'_x'],arr[direction+'_y'] = x,y
            for nm in ('NodeVolume','Donors','Acceptors','NetDoping'):
                arr[direction+'_'+nm] = np.array(dv.get_node_model_values(device=name,region='Si',name=nm))
            for nm in ('x@n0','x@n1','y@n0','y@n1','EdgeLength','EdgeCouple'):
                arr[direction+'_'+nm] = np.array(dv.get_edge_model_values(device=name,region='Si',name=nm))
            arr[direction+'_elements'] = np.array(dv.get_element_node_list(device=name,region='Si'))
            for bias in M.SNAP_BIASES[direction]:
                hit = [s for s in obs.snaps if s['has_DD'] and abs(s['bias_min']-bias)<1e-12 and s['bias_max']==0]
                if not hit:
                    raise RuntimeError('SNAPSHOT_MISSING')
                for nm in M.SNAP_ARRAYS:
                    arr[f'{direction}_{bias}_{nm}'] = hit[-1][nm]
        except Exception as exc:
            dr['error'] = type(exc).__name__+': '+str(exc).replace(str(ROOT),'<REPO>')[:800]
        finally:
            if obs is not None:
                dr.update(solve_attempts=obs.solve_attempts,solves=obs.solves,solve_failures=obs.solve_failures,snapshot_failures=obs.snapshot_failures)
                obs.restore()
            cleanup(dv,name,mesh,dr)
            save(out/'record.json',rec)
            np.savez_compressed(out/'arrays.npz',**arr)
        if dr['error'] or not dr['cleanup_ok']:
            return 1
    return 0


def main():
    require_plan()
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        return worker(int(sys.argv[2]),Path(sys.argv[3]))
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or os.name!='nt':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    from resource_supervisor import supervise
    from judge import judge
    out = ROOT/'e6nd_out'
    out.mkdir(exist_ok=True)
    records = []
    deadline = time.monotonic()+1800
    for level in range(2):
        rec = supervise([sys.executable,'-B',str(__file__),'--worker',str(level),str(out/f'N{level}')],ROOT,out/f'N{level}.log',candidate_s=900,total_deadline=deadline)
        records.append(rec)
        if rec['status']!='COMPLETED' or not rec['cleanup_ok']:
            break
    save(out/'execution.json',{'plan_sha256':PLAN_SHA,'supervisors':records,'pn_production_approved':False})
    result = judge(out)
    save(out/'result.json',result)
    print(json.dumps(result,indent=2),flush=True)
    return 0 if result['status']=='PILOT_PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
