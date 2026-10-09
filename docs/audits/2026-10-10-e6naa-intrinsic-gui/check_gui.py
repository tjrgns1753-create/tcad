"""고정 PLAN의 실제 GUI 경로. 원격에서만 엔진과 Tk를 사용한다."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PLAN_SHA='341c4413b363c8ec6a7501da2d3853b17ce849222c9ef8007c21cf95487021bb'

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
    if hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH_BEFORE_ENGINE_IMPORT')
    sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration')]
    import test_uniform_resistor_dd_current_real as base
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields
    from tcad.characterization.intrinsic import known_undoped_si
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe
    from tcad.physics.wafer_state_v2 import advance
    dv=backend.require_devsim()
    out=ROOT/'e6naa_out'; out.mkdir(exist_ok=True)
    path=base.write_mesh(*base.mesh_arrays('one_sided',8),'intrinsic_gui')
    virgin=lambda: initial_wafer_state_from_recipe({'x_extent_um':2.,'silicon_depth_um':.5,'grid_delta_um':.25})
    records={'cases':{},'blocked':{},'plan_sha':PLAN_SHA}
    live={}; capture_original=node_fields.capture_node_fields
    def capture(module,device,region,scale):
        fields=capture_original(module,device,region,scale)
        for key,name in node_fields.FIELD_NAMES.items():
            assert tuple(module.get_node_model_values(device=device,region=region,name=name))==getattr(fields,key)
        live['params']={k:float(module.get_parameter(device=device,region=region,name=k)) for k in ('ElectronCharge','n_i','T','mu_n','mu_p','taun','taup')}
        live['doping']={k:list(module.get_node_model_values(device=device,region=region,name=k)) for k in ('Donors','Acceptors','NetDoping')}
        live['captures']=live.get('captures',0)+1
        return fields
    node_fields.capture_node_fields=capture
    modal=[]; saved={k:getattr(gui.messagebox,k) for k in base.MESSAGEBOX if hasattr(gui.messagebox,k)}
    for k in saved: setattr(gui.messagebox,k,lambda *a,**kw: modal.append(True))
    dialog_original=gui.filedialog.asksaveasfilename
    app=gui.TCADApplication(); app.withdraw(); errors=[]
    app._notify_error=lambda *a: errors.append(str(a))
    def save(): (out/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    try:
        for name,axis,v in (('x_zero','x',0.),('x_positive','x',.001),('x_negative','x',-.001),('y_positive','y',.00025),('fresh_gui','x',.001)):
            app.reset(); live.clear(); start_errors=len(errors)
            app.wafer.width_um=2.; app.wafer.silicon_depth_um=.5; app.grid_var.set(.25)
            if name!='fresh_gui': app.wafer_state=virgin(); app.last_final_mesh=path
            app.last_doped_result=None
            app.meas_axis_var.set(axis); app.meas_source_pin.set('max'); app.meas_voltage_var.set(v)
            history=len(app.history); obs=base.Observer(dv); obs.install()
            try: app.run_measurement()
            finally: obs.restore()
            assert len(errors)==start_errors,(name,errors[start_errors:])
            fields,result=app._measurement_fields,app._measurement_fields_result
            assert fields is not None and result is not None and obs.solves==3,(name,obs.solves)
            assert known_undoped_si(app.wafer_state) and app.last_doped_result is None
            assert result.metadata['device_input']=='CANONICAL_KNOWN_UNDOPED'
            assert len(app.history)==history+1 and live['captures']==1
            assert all(a==0. for values in live['doping'].values() for a in values)
            rendered={}
            for layer in node_fields.FIELD_NAMES:
                app.viewer_layer_var.set(layer); app.redraw()
                notes=app.canvas.find_withtag('solved_field_note')
                assert len(notes)==1
                rendered[layer]={'nodes':len(app.canvas.find_withtag('solved_field_node')),'text':app.canvas.itemcget(notes[0],'text')}
                assert rendered[layer]['nodes']==len(fields.xy_um)
            target=out/(name+'_fields.json'); gui.filedialog.asksaveasfilename=lambda **kw:str(target)
            app._on_export_node_fields_clicked(); assert target.is_file()
            export=json.loads(target.read_text(encoding='utf-8'))
            assert export['snapshot']==json.loads(json.dumps(asdict(fields)))
            assert export['measurement']['currents']==result.points[0].currents
            records['cases'][name]={'axis':axis,'voltage':v,'snapshot':asdict(fields),'measurement':asdict(result),
                'params':dict(live['params']),'doping':dict(live['doping']),'solves':obs.solves,
                'captures':live['captures'],'attachments':len(app.wafer_state.attachments),'rendered':rendered,
                'export_equal':True,'live_api_equal':True,'history_delta':len(app.history)-history,
                'devices_after':list(dv.get_device_list()),'meshes_after':list(dv.get_mesh_list())}
            assert not dv.get_device_list() and not dv.get_mesh_list() and not modal
            save(); print('PASS',name,result.points[0].currents,flush=True)
        for name in ('high_field','unresolved','chemical','active_missing_profile'):
            app.reset(); live.clear(); app.last_final_mesh=path; app.last_doped_result=None
            if name=='unresolved': state=advance(virgin(),None,step_seed='etching')
            elif name in ('chemical','active_missing_profile'): state,_=base.canonical(path,'CHEMICAL' if name=='chemical' else 'ACTIVE')
            else: state=virgin()
            app.wafer_state=state; app.meas_axis_var.set('x'); app.meas_voltage_var.set(.002 if name=='high_field' else .001)
            history=len(app.history); obs=base.Observer(dv); obs.install()
            try: app.run_measurement()
            finally: obs.restore()
            assert obs.solves==0 and len(obs.writes)==0 and not live and app._measurement_fields is None
            assert app.wafer_state is state and app.last_doped_result is None and len(app.history)==history
            assert not dv.get_device_list() and not dv.get_mesh_list() and not modal
            records['blocked'][name]={'solves':obs.solves,'writes':len(obs.writes),'captures':0,'history_delta':0,'fields_none':True,'state_identity':True}
            save(); print('PASS refusal',name,flush=True)
        (out/'verdict.json').write_text(json.dumps({'pass':True,'cases':5,'refusals':4,'solves':15}),encoding='utf-8')
        return 0
    finally:
        app.destroy(); node_fields.capture_node_fields=capture_original
        gui.filedialog.asksaveasfilename=dialog_original
        for k,fn in saved.items(): setattr(gui.messagebox,k,fn)

if __name__=='__main__': raise SystemExit(main())
