"""원격 실제 uniform DD 노드 보존 및 Tk 표시. PN 승인이 아니다."""
import json
import os
from pathlib import Path
import sys
from dataclasses import asdict
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/integration'))

def main():
    if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':raise RuntimeError('REMOTE_ONLY')
    import test_uniform_resistor_dd_current_real as base
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields
    import tcad_2d_stagewise as gui
    dv=backend.require_devsim()
    P,T=base.mesh_arrays('one_sided',8);path=base.write_mesh(P,T,'node_fields')
    state,doped=base.canonical(path,'ACTIVE')
    original=node_fields.capture_node_fields;live={}
    def capture(module,device,region,scale):
        snapshot=original(module,device,region,scale)
        for key,name in node_fields.FIELD_NAMES.items():
            a=tuple(float(v) for v in module.get_node_model_values(device=device,region=region,name=name))
            assert a==getattr(snapshot,key)
            live[key]=a
        assert snapshot.xy_um==tuple(zip(
            [v/scale for v in module.get_node_model_values(device=device,region=region,name='x')],
            [v/scale for v in module.get_node_model_values(device=device,region=region,name='y')]))
        return snapshot
    node_fields.capture_node_fields=capture
    saved={n:getattr(gui.messagebox,n) for n in base.MESSAGEBOX if hasattr(gui.messagebox,n)}
    for n in saved:setattr(gui.messagebox,n,lambda *a,**k:None)
    app=gui.TCADApplication();obs=base.Observer(dv)
    try:
        app.withdraw();app.meas_voltage_var.set(.001);app.meas_axis_var.set('x');app.meas_source_pin.set('max')
        app.last_final_mesh=path;app.last_doped_result=doped;app.wafer_state=state
        obs.install()
        try:app.run_measurement()
        finally:obs.restore()
        fields=app._measurement_fields
        assert fields is not None and not dv.get_device_list() and obs.solves==3
        assert all(tuple(getattr(fields,k))==live[k] for k in live)
        xy=np.array(fields.xy_um);phi=np.array(fields.potential)
        x=xy[:,0];ref=phi[x==x.min()].mean()
        psi_error=float(np.max(np.abs(phi-(ref+.001*(x-x.min())/(x.max()-x.min()))))/.001)
        assert psi_error<=1e-6  # Existing uniform resistor criterion; not a new PN tolerance.
        assert min(fields.electron)>0 and min(fields.hole)>0
        rendered={}
        for layer in node_fields.FIELD_NAMES:
            app.viewer_layer_var.set(layer);app.redraw()
            nodes=app.canvas.find_withtag('solved_field_node')
            notes=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('solved_field_note')]
            assert len(nodes)==len(fields.xy_um) and any('No interpolation' in n for n in notes)
            rendered[layer]={'nodes':len(nodes),'notes':notes}
        app.meas_voltage_var.set('.002');app.redraw()
        assert not app.canvas.find_withtag('solved_field_node')
        app.meas_voltage_var.set('nan');app.run_measurement()
        assert app._measurement_fields is None and not app.canvas.find_withtag('solved_field_node')
        out=ROOT/'e6nm_out';out.mkdir(exist_ok=True)
        (out/'fields.json').write_text(json.dumps({'pass':True,'solves':obs.solves,'psi_linear_relative_error':psi_error,
            'snapshot':asdict(fields),'rendered':rendered,'device_cleanup':not dv.get_device_list(),
            'capture_equals_live_api':True,'failed_retry_has_no_fields':True},indent=2),encoding='utf-8')
        print('PASS actual uniform DD snapshot equals live public API; all node dots; stale and failed retry blocked')
    finally:
        app.destroy();node_fields.capture_node_fields=original
        for n,fn in saved.items():setattr(gui.messagebox,n,fn)
    return 0
if __name__=='__main__':raise SystemExit(main())
