"""실제 노드 지도에서 Tk hover가 실제 값을 읽는지 확인한다."""
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
    from tcad.characterization.node_fields import FIELD_UNITS
    import tcad_2d_stagewise as gui
    dv=backend.require_devsim();P,T=base.mesh_arrays('one_sided',8);path=base.write_mesh(P,T,'hover')
    state,doped=base.canonical(path,'ACTIVE')
    saved={n:getattr(gui.messagebox,n) for n in base.MESSAGEBOX if hasattr(gui.messagebox,n)}
    for n in saved:setattr(gui.messagebox,n,lambda *a,**k:None)
    app=gui.TCADApplication();obs=base.Observer(dv)
    try:
        app.withdraw();app.meas_voltage_var.set(.001);app.meas_axis_var.set('x');app.meas_source_pin.set('max')
        app.last_final_mesh=path;app.last_doped_result=doped;app.wafer_state=state
        obs.install()
        try:app.run_measurement()
        finally:obs.restore()
        f=app._measurement_fields;assert f is not None and obs.solves==3 and not dv.get_device_list()
        readouts={}
        # A real node chosen by fixed index, not by values or a fitted location.
        index=0;x,y=f.xy_um[index]
        for layer in FIELD_UNITS:
            app.viewer_layer_var.set(layer);app.redraw()
            cx0,xmin,xs,sy,ys=app._viewer_scale
            event=S(x=cx0+(x-xmin)*xs,y=sy-y*ys)
            app._on_canvas_motion(event);text=app.coord_var.get()
            assert f'{getattr(f,layer)[index]:.6e} {FIELD_UNITS[layer]}' in text and '보간 아님' in text
            readouts[layer]={'node_index':index,'xy_um':[x,y],'raw_value':getattr(f,layer)[index],'text':text}
            app._on_canvas_motion(S(x=-1000,y=-1000));assert '보간 아님' not in app.coord_var.get()
        app.meas_voltage_var.set('.002')
        app._on_canvas_motion(event);assert '보간 아님' not in app.coord_var.get()
        app.reset()
        assert app._measurement_fields is app._measurement_fields_context is app._measurement_fields_settings is None
        assert not app.canvas.find_withtag('solved_field_node') and not dv.get_device_list()
        out=ROOT/'e6nn_out';out.mkdir(exist_ok=True)
        (out/'hover.json').write_text(json.dumps({'pass':True,'solves':obs.solves,'readouts':readouts,
            'reset_cleared':True,'outside_no_value':True,'stale_no_value':True,'device_cleanup':True},indent=2),encoding='utf-8')
        print('PASS actual Tk mouse handler reads actual node value/units; outside/stale blocked; reset clears')
    finally:
        app.destroy()
        for n,fn in saved.items():setattr(gui.messagebox,n,fn)
    return 0
if __name__=='__main__':raise SystemExit(main())
