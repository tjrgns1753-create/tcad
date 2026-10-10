"""실제 원격 Tk canvas의 모델 경계/원노드 색/좌표 확인. calibration 승인 아님."""
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_measurement_canonical_state_gate_real import _measure, _configure, _assert_supported
from tcad.characterization.node_fields import field_samples, field_caption
from tcad.characterization.transport_evidence import transport_model_scope


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    app = gui.TCADApplication()
    modal = []
    methods = ('showinfo', 'showerror', 'showwarning', 'askquestion', 'askyesno',
               'askyesnocancel', 'askokcancel', 'askretrycancel')
    saved = {n: getattr(gui.messagebox, n) for n in methods}
    for n in methods:
        setattr(gui.messagebox, n, lambda *a, _name=n, **kw: modal.append(_name) or True)
    out = ROOT/'e6nai_canvas_out'
    out.mkdir(exist_ok=True)
    metrics = {}
    try:
        app.geometry('1280x900')
        app.update()
        for label, donor, acceptor, voltage in (
                ('n', 1e16, 0., .01), ('p', 0., 5e15, .01), ('intrinsic', 0., 0., .001)):
            app.reset()
            _configure(app)
            app.meas_voltage_var.set(voltage)
            assert app._materialize_current_wafer()
            if label != 'intrinsic':
                app.doping_kind.set('Uniform')
                app.dope_uniform_region_var.set('Si')
                app.dope_uniform_donor_var.set(donor)
                app.dope_uniform_acceptor_var.set(acceptor)
                assert app.run_doping()
            b = _measure(app, dv, label)
            if label != 'intrinsic': _assert_supported(label, b)
            assert b['solve_calls'] == 3 and not dv.get_device_list(), b
            fields = app._measurement_fields
            result = app._measurement_fields_result
            original = (fields.xy_um, fields.potential, fields.electron, fields.hole)
            layers = {}
            for layer in ('potential', 'electron', 'hole'):
                app.viewer_layer_var.set(layer)
                app.redraw()
                app.update()
                nodes = app.canvas.find_withtag('solved_field_node')
                notes = app.canvas.find_withtag('solved_field_note')
                samples, _, _ = field_samples(fields, layer)
                assert len(nodes) == len(samples) and len(notes) == 1
                caption = app.canvas.itemcget(notes[0], 'text')
                assert caption == field_caption(fields, result, layer)
                assert transport_model_scope(result.metadata) in caption
                cx0, xmin, xs, sy, ys = app._viewer_scale
                for item, (x, y, value, color) in zip(nodes, samples):
                    rect = app.canvas.coords(item)
                    cx, cy = cx0+(x-xmin)*xs, sy-y*ys
                    # Rendering arithmetic, not a physical/mesh tolerance.
                    assert abs((rect[0]+rect[2])/2-cx) <= 4*math.ulp(max(abs(cx), 1.))
                    assert abs((rect[1]+rect[3])/2-cy) <= 4*math.ulp(max(abs(cy), 1.))
                    assert app.canvas.itemcget(item, 'fill') == color
                assert original == (fields.xy_um, fields.potential, fields.electron, fields.hole)
                bbox = app.canvas.bbox(notes[0])
                size = (app.canvas.winfo_width(), app.canvas.winfo_height())
                assert 0 <= bbox[0] < bbox[2] <= size[0] and 0 <= bbox[1] < bbox[3] <= size[1], (bbox, size, caption)
                screenshot = 'NOT_CAPTURED'
                try:
                    from PIL import ImageGrab
                    x, y = app.canvas.winfo_rootx(), app.canvas.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x+size[0], y+size[1])).save(out/(label+'_'+layer+'.png'))
                    screenshot = 'CAPTURED_CANVAS'
                except OSError:
                    # Optional visual record; actual canvas assertions are mandatory.
                    screenshot = 'DESKTOP_CAPTURE_UNAVAILABLE'
                layers[layer] = {'nodes': len(nodes), 'caption': caption, 'bbox': bbox,
                                 'canvas_size': size, 'screenshot': screenshot}
            metrics[label] = {'solve_calls': b['solve_calls'], 'layers': layers, 'arrays_unchanged': True}
        assert not modal and not dv.get_device_list()
        (out/'metrics.json').write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding='utf-8')
        print('PASS: 9 actual canvas layers, original arrays/pixels/colors, model scope and unclipped captions')
    finally:
        for n, fn in saved.items(): setattr(gui.messagebox, n, fn)
        app.destroy()


if __name__ == '__main__': main()
