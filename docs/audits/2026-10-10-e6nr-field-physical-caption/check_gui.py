"""실제 uniform Si의 원시 Potential 기준과 source-bound caption. 원격만."""
from dataclasses import asdict
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/integration'))


def main():
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    import test_uniform_resistor_dd_current_real as base
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields
    from devsim.python_packages.simple_physics import CreateSiliconPotentialOnlyContact
    import tcad_2d_stagewise as gui
    dv = backend.require_devsim()
    points, triangles = base.mesh_arrays('one_sided', 8)
    path = base.write_mesh(points, triangles, 'field_export')
    state, doped = base.canonical(path, 'ACTIVE')
    original = node_fields.capture_node_fields
    live = {}

    def capture(module, device, region, scale):
        fields = original(module, device, region, scale)
        live['snapshot'] = asdict(fields)
        for key, name in node_fields.FIELD_NAMES.items():
            assert tuple(module.get_node_model_values(device=device, region=region, name=name)) == getattr(fields, key)
        live['V_t'] = float(module.get_parameter(device=device, region=region, name='V_t'))
        live['n_i'] = float(module.get_parameter(device=device, region=region, name='n_i'))
        live['NetDoping'] = list(module.get_node_model_values(device=device, region=region, name='NetDoping'))
        return fields

    node_fields.capture_node_fields = capture
    saved = {name: getattr(gui.messagebox, name) for name in base.MESSAGEBOX if hasattr(gui.messagebox, name)}
    for name in saved:
        setattr(gui.messagebox, name, lambda *a, **kw: None)
    app = gui.TCADApplication()
    observer = base.Observer(dv)
    out = ROOT / 'e6nr_out'
    out.mkdir(exist_ok=True)
    old_dialog = gui.filedialog.asksaveasfilename
    target = out / '실제노드.json'
    gui.filedialog.asksaveasfilename = lambda **kw: str(target)
    try:
        app.withdraw()
        app.last_final_mesh = path
        app.last_doped_result = doped
        app.wafer_state = state
        app.meas_voltage_var.set(.001)
        app.meas_axis_var.set('x')
        app.meas_source_pin.set('max')
        observer.install()
        try:
            app.run_measurement()
        finally:
            observer.restore()
        fields = app._measurement_fields
        result = app._measurement_fields_result
        assert fields is not None and result is not None and observer.solves == 3
        assert not dv.get_device_list()
        assert json.loads(json.dumps(asdict(fields))) == json.loads(json.dumps(live['snapshot']))
        voltages = result.points[0].voltages
        assert voltages['Si_xmin'] == 0 and voltages['Si_xmax'] == .001
        xmin = min(x for x, y in fields.xy_um)
        ground = [i for i, (x, y) in enumerate(fields.xy_um) if x == xmin]
        assert ground and all(live['NetDoping'][i] > 0 for i in ground)
        expected = [live['V_t'] * math.log((1e-10 + .5 * abs(live['NetDoping'][i] +
                    math.sqrt(live['NetDoping'][i] ** 2 + 4 * live['n_i'] ** 2))) / live['n_i']) for i in ground]
        error = max(abs(fields.potential[i] - reference) for i, reference in zip(ground, expected))
        assert error <= 1e-9
        rendered = {}
        for layer in node_fields.FIELD_NAMES:
            app.viewer_layer_var.set(layer)
            app.redraw()
            dots = app.canvas.find_withtag('solved_field_node')
            notes = app.canvas.find_withtag('solved_field_note')
            assert len(dots) == 73 and len(notes) == 1
            text = app.canvas.itemcget(notes[0], 'text')
            assert '영역 Si' in text and 'Si_xmin=+0 V' in text and 'Si_xmax=+0.001 V' in text
            assert 'No interpolation' in text and ('원시 Potential' in text) == (layer == 'potential')
            assert app.canvas.itemcget(notes[0], 'anchor') == 's'
            rendered[layer] = {'nodes': len(dots), 'text': text, 'bbox': app.canvas.bbox(notes[0])}
        app._on_export_node_fields_clicked()
        assert target.is_file()
        payload = json.loads(target.read_text(encoding='utf-8'))
        prior = json.loads((ROOT / 'docs/audits/2026-10-10-e6nq-field-contact-evidence/raw/outputs/e6no_out/실제노드.json').read_text(encoding='utf-8'))
        assert payload == prior
        app.meas_voltage_var.set('.002')
        assert not app.canvas.find_withtag('solved_field_node')
        records = {'pass': True, 'solves': observer.solves, 'live_api_equal': True,
            'device_cleanup': not dv.get_device_list(), 'snapshot': asdict(fields), 'voltages': voltages,
            'rendered': rendered, 'V_t': live['V_t'], 'n_i': live['n_i'], 'NetDoping': live['NetDoping'],
            'ground_indices': ground, 'ground_expected': expected, 'ground_formula_error_V': error,
            'ground_applied_V': 0, 'ground_raw_potential_V': fields.potential[ground[0]],
            'official_contact_helper_sha256': hashlib.sha256(inspect.getsource(CreateSiliconPotentialOnlyContact).encode()).hexdigest(),
            'export_unchanged': True, 'file_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        (out / 'caption.json').write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
        print('PASS actual captions/region/bias; raw Potential equals official ohmic expression; full export unchanged')
    finally:
        app.destroy()
        node_fields.capture_node_fields = original
        gui.filedialog.asksaveasfilename = old_dialog
        for name, callback in saved.items():
            setattr(gui.messagebox, name, callback)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
