"""실제 uniform DD 노드 증거의 GUI export. 새 물리 승인 없음."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/integration'))
def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':raise RuntimeError('REMOTE_ONLY')
    import test_uniform_resistor_dd_current_real as base
    from tcad.device.devsim import backend
    import tcad.characterization.pn_junction_iv_sweep as sweep
    import tcad_2d_stagewise as gui
    dv=backend.require_devsim();P,T=base.mesh_arrays('one_sided',8);path=base.write_mesh(P,T,'field_export')
    st,doped=base.canonical(path,'ACTIVE')
    saved={n:getattr(gui.messagebox,n) for n in base.MESSAGEBOX if hasattr(gui.messagebox,n)}
    for n in saved:setattr(gui.messagebox,n,lambda *a,**k:None)
    original=sweep.run_pn_junction_iv_sweep;original_results=[]
    def observe(**kw):
        result=original(**kw);original_results.append(result);return result
    sweep.run_pn_junction_iv_sweep=observe
    dialog=gui.filedialog.asksaveasfilename;app=gui.TCADApplication();obs=base.Observer(dv)
    out=ROOT/'e6no_out';out.mkdir(exist_ok=True);target=out/'실제노드.json';calls=[]
    gui.filedialog.asksaveasfilename=lambda **kw:calls.append(kw) or str(target)
    try:
        app.withdraw();app.last_final_mesh=path;app.last_doped_result=doped;app.wafer_state=st
        app.meas_voltage_var.set(.001);app.meas_axis_var.set('x');app.meas_source_pin.set('max')
        obs.install()
        try:app.run_measurement()
        finally:obs.restore()
        f=app._measurement_fields;r=app._measurement_fields_result
        assert f is not None and r is not original_results[0] and r.points[0] is not original_results[0].points[0]
        assert obs.solves==3 and not dv.get_device_list()
        app._on_export_node_fields_clicked();assert len(calls)==1 and target.is_file()
        payload=json.loads(target.read_text(encoding='utf-8'))
        assert payload['snapshot']==json.loads(json.dumps(asdict(f)))
        assert payload['measurement']['voltages']==r.points[0].voltages and payload['measurement']['currents']==r.points[0].currents
        assert payload['measurement']['metadata']['current_unit']=='A/cm' and payload['node_count']==73
        assert payload['source_evidence']['mesh_sha256']==hashlib.sha256(Path(path).read_bytes()).hexdigest()
        before=target.read_bytes()
        app.viewer_layer_var.set('potential');app.redraw();assert len(app.canvas.find_withtag('solved_field_node'))==73
        cx0,xmin,xs,sy,ys=app._viewer_scale;x,y=f.xy_um[0]
        app._on_canvas_motion(S(x=cx0+(x-xmin)*xs,y=sy-y*ys))
        readout=app.coord_var.get();assert '보간 아님' in readout
        app.meas_voltage_var.set('.002')  # write trace must invalidate without manual redraw
        assert not app.canvas.find_withtag('solved_field_node')
        assert app.coord_var.get()==''
        app._on_export_node_fields_clicked();assert len(calls)==1 and target.read_bytes()==before
        app.meas_voltage_var.set('nan');app.run_measurement()
        assert app._measurement_fields_result is app._measurement_fields is None
        app._on_export_node_fields_clicked();assert len(calls)==1
        # Deliberately restore the old real readout as a UI fault fixture;
        # resetting must clear it even with no further mouse event.
        app.coord_var.set(readout);app.reset();assert app.coord_var.get()==''
        assert not list(out.glob('*.tmp'))
        (out/'export.json').write_text(json.dumps({'pass':True,'solves':obs.solves,'node_count':73,
            'file_sha256':hashlib.sha256(before).hexdigest(),'source_mesh_sha256':payload['source_evidence']['mesh_sha256'],
            'all_arrays_equal':True,'all_contact_bias_currents_equal':True,'result_deepcopied':True,
            'stale_blocked_before_dialog':True,'write_trace_hides_old_map':True,'failed_retry_blocks_export':True,
            'redraw_cleared_readout':True,'reset_fault_fixture_cleared_readout':True,
            'device_cleanup':not dv.get_device_list()},indent=2),encoding='utf-8')
        print('PASS actual field export arrays/bias/units/source; trace clears stale display; failed retry/dialog blocked')
    finally:
        app.destroy();sweep.run_pn_junction_iv_sweep=original;gui.filedialog.asksaveasfilename=dialog
        for n,fn in saved.items():setattr(gui.messagebox,n,fn)
    return 0
if __name__=='__main__':raise SystemExit(main())
