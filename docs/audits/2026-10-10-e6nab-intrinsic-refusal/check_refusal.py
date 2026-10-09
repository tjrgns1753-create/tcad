"""실제 공식 solve 뒤 감사용으로 손상 값을 주입한다. 엔진 오류로 집계하지 않는다."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PLAN_SHA='6b0d1be28bad2b658fbf2dc1623e9fa5ba8105d706391142a0fbf6f34c49ec02'

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
    if hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH_BEFORE_ENGINE_IMPORT')
    sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration')]
    import test_uniform_resistor_dd_current_real as base
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields, pn_junction_iv_sweep
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe
    dv=backend.require_devsim(); out=ROOT/'e6nab_out'; out.mkdir(exist_ok=True)
    path=base.write_mesh(*base.mesh_arrays('one_sided',8),'intrinsic_refusal')
    state=lambda:initial_wafer_state_from_recipe({'x_extent_um':2.,'silicon_depth_um':.5,'grid_delta_um':.25})
    capture_original=node_fields.capture_node_fields; sweep_original=pn_junction_iv_sweep.run_pn_junction_iv_sweep
    live={}; fault=[None]; errors=[]; modal=[]; records={'supported':{},'faults':{},'plan_sha':PLAN_SHA}
    def capture(module,device,region,scale):
        f=capture_original(module,device,region,scale)
        for key,name in node_fields.FIELD_NAMES.items():
            assert tuple(module.get_node_model_values(device=device,region=region,name=name))==getattr(f,key)
        live['original_fields']=asdict(f); live['captures']=live.get('captures',0)+1
        live['params']={k:float(module.get_parameter(device=device,region=region,name=k)) for k in ('ElectronCharge','n_i','mu_n','mu_p')}
        if fault[0]=='electron_zero': return replace(f,electron=(0.,)*len(f.electron))
        if fault[0]=='potential_flat': return replace(f,potential=(0.,)*len(f.potential))
        if fault[0]=='geometry_shift': return replace(f,xy_um=tuple((x,y+.25) for x,y in f.xy_um))
        if fault[0]=='capture_unavailable': raise ValueError('AUDIT_INJECTED_CAPTURE_ERROR')
        return f
    def sweep(*a,**kw):
        r=sweep_original(*a,**kw); live['original_result']=asdict(r)
        if fault[0]=='current_doubled':
            p=r.points[0]
            return replace(r,points=[replace(p,currents={k:2*v for k,v in p.currents.items()})])
        return r
    node_fields.capture_node_fields=capture; pn_junction_iv_sweep.run_pn_junction_iv_sweep=sweep
    saved={k:getattr(gui.messagebox,k) for k in base.MESSAGEBOX if hasattr(gui.messagebox,k)}
    for k in saved: setattr(gui.messagebox,k,lambda *a,**kw:modal.append(True))
    dialog_original=gui.filedialog.asksaveasfilename
    app=gui.TCADApplication(); app.withdraw(); app._notify_error=lambda *a:errors.append(str(a))
    def setup(axis,v,side='max'):
        app.reset(); live.clear(); app.wafer_state=state(); app.last_final_mesh=path; app.last_doped_result=None
        app.meas_axis_var.set(axis); app.meas_source_pin.set(side); app.meas_voltage_var.set(v)
        app.last_physics_status={'resolution':'MODELLED','reason_code':'OLD_RESULT'}
    def save(): (out/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    try:
        for name,axis,v in (('x_min_positive','x',.001),('x_min_negative','x',-.001),('y_min_negative','y',-.00025)):
            fault[0]=None; setup(axis,v,'min'); history=len(app.history); nerr=len(errors)
            obs=base.Observer(dv); obs.install()
            try:app.run_measurement()
            finally:obs.restore()
            assert len(errors)==nerr and app._measurement_fields is not None and obs.solves==3
            fields,result=app._measurement_fields,app._measurement_fields_result
            assert len(app.history)==history+1 and result.metadata['device_input']=='CANONICAL_KNOWN_UNDOPED'
            target=out/(name+'_fields.json'); gui.filedialog.asksaveasfilename=lambda **kw:str(target)
            app._on_export_node_fields_clicked(); export=json.loads(target.read_text(encoding='utf-8'))
            assert export['snapshot']==json.loads(json.dumps(asdict(fields)))
            assert export['measurement']['currents']==result.points[0].currents
            records['supported'][name]={'axis':axis,'voltage':v,'side':'min','solves':obs.solves,
                'snapshot':asdict(fields),'measurement':asdict(result),'params':dict(live['params']),
                'history_delta':len(app.history)-history,'export_equal':True,
                'devices_after':list(dv.get_device_list()),'meshes_after':list(dv.get_mesh_list())}
            save(); print('PASS supported',name,flush=True)
        for name in ('electron_zero','potential_flat','geometry_shift','capture_unavailable','current_doubled','high_field'):
            fault[0]=None if name=='high_field' else name; setup('x',.002 if name=='high_field' else .001)
            history=len(app.history); nerr=len(errors); log=app.log.get('1.0','end-1c'); canonical=app.wafer_state
            obs=base.Observer(dv); obs.install()
            try:app.run_measurement()
            finally:obs.restore()
            assert len(errors)==nerr+1 and app.wafer_state is canonical
            assert app._measurement_fields is app._measurement_fields_context is app._measurement_fields_result is None
            assert len(app.history)==history and 'DEVSIM MEASUREMENT' not in app.log.get('1.0','end-1c')[len(log):]
            assert app.last_physics_status['resolution']=='UNSUPPORTED_BY_MODEL'
            expected='INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED' if name=='high_field' else 'INTRINSIC_RESULT_NOT_VALIDATED'
            assert app.last_physics_status['reason_code']==expected
            assert obs.solves==(0 if name=='high_field' else 3)
            assert not dv.get_device_list() and not dv.get_mesh_list() and not modal
            records['faults'][name]={'kind':'PREFLIGHT' if name=='high_field' else 'AUDIT_FAULT_INJECTION',
                'solves':obs.solves,'writes':len(obs.writes),'captures':live.get('captures',0),
                'state_identity':app.wafer_state is canonical,'history_delta':0,'field_result_none':True,
                'success_log_absent':True,'status':app.last_physics_status,'original_api_evidence':dict(live),
                'devices_after':list(dv.get_device_list()),'meshes_after':list(dv.get_mesh_list())}
            if name=='high_field':assert not live and not obs.writes
            save(); print('PASS refusal',name,flush=True)
        (out/'verdict.json').write_text(json.dumps({'pass':True,'supported':3,'fault_injections':5,'preflight':1,'actual_solves':24}),encoding='utf-8')
        return 0
    finally:
        app.destroy(); node_fields.capture_node_fields=capture_original
        pn_junction_iv_sweep.run_pn_junction_iv_sweep=sweep_original; gui.filedialog.asksaveasfilename=dialog_original
        for k,fn in saved.items():setattr(gui.messagebox,k,fn)

if __name__=='__main__':raise SystemExit(main())
