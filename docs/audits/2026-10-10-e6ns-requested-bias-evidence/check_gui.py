"""정상 실제 DD 및 성공 후 기록 변조 방어 검사. 엔진은 원격만."""
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/integration'))


def main():
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    import test_uniform_resistor_dd_current_real as base
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields
    import tcad.characterization.pn_junction_iv_sweep as sweep
    import tcad_2d_stagewise as gui
    dv = backend.require_devsim()
    path = base.write_mesh(*base.mesh_arrays('one_sided', 8), 'field_export')
    out = ROOT / 'e6ns_out'
    out.mkdir(exist_ok=True)
    target = out / '실제노드.json'
    original = sweep.run_pn_junction_iv_sweep
    saved = {name: getattr(gui.messagebox, name) for name in base.MESSAGEBOX if hasattr(gui.messagebox, name)}
    for name in saved:
        setattr(gui.messagebox, name, lambda *a, **kw: None)
    app = gui.TCADApplication()
    app.withdraw()
    errors, dialog_calls, capture_calls = [], [], []
    app._notify_error = lambda *args: errors.append(str(args))
    old_dialog = gui.filedialog.asksaveasfilename
    gui.filedialog.asksaveasfilename = lambda **kw: dialog_calls.append(kw) or str(target)
    records = {}
    try:
        for label in ('normal', 'wrong_source_voltage', 'wrong_ground_voltage'):
            state, doped = base.canonical(path, 'ACTIVE')
            app.last_final_mesh = path
            app.last_doped_result = doped
            app.wafer_state = state
            app.meas_voltage_var.set(.001)
            app.meas_axis_var.set('x')
            app.meas_source_pin.set('max')
            before_errors = len(errors)
            history_len = len(app.history)
            before_log = app.log.get('1.0', 'end-1c')
            observed = {}

            def return_result(**kwargs):
                result = original(**kwargs)
                observed['original_voltages'] = dict(result.points[0].voltages)
                if label == 'wrong_source_voltage':
                    result.points[0].voltages[result.sweep_contact] = .002
                elif label == 'wrong_ground_voltage':
                    ground = next(c for c in result.points[0].voltages if c != result.sweep_contact)
                    result.points[0].voltages[ground] = .1
                observed['returned_voltages'] = dict(result.points[0].voltages)
                return result

            def trap_capture(*args, **kwargs):
                capture_calls.append(label)
                raise AssertionError('MISMATCH_MUST_STOP_BEFORE_FIELD_CAPTURE')

            observer = base.Observer(dv)
            observer.install()
            try:
                with patch.object(sweep, 'run_pn_junction_iv_sweep', return_result):
                    if label == 'normal':
                        app.run_measurement()
                    else:
                        with patch.object(node_fields, 'capture_node_fields', trap_capture):
                            app.run_measurement()
            finally:
                observer.restore()
            log = app.log.get('1.0', 'end-1c')[len(before_log):]
            assert observer.solves == 3 and not dv.get_device_list()
            assert observed['original_voltages'] == {'Si_xmin': 0., 'Si_xmax': .001}
            if label == 'normal':
                assert len(errors) == before_errors and 'DEVSIM MEASUREMENT' in log
                assert len(app.history) == history_len + 1
                assert app._measurement_fields is not None and app._measurement_fields_result is not None
                app._on_export_node_fields_clicked()
                before_file = target.read_bytes()
                payload = json.loads(before_file)
                prior = json.loads((ROOT / 'docs/audits/2026-10-10-e6nr-field-physical-caption/raw/outputs/e6nr_out/실제노드.json').read_text(encoding='utf-8'))
                assert payload == prior
            else:
                assert len(errors) == before_errors + 1 and 'DEVSIM MEASUREMENT' not in log
                assert len(app.history) == history_len
                assert app._measurement_fields is app._measurement_fields_result is None
                assert not capture_calls
                app.viewer_layer_var.set('potential')
                app.redraw()
                assert not app.canvas.find_withtag('solved_field_node')
                app._on_export_node_fields_clicked()
                assert len(dialog_calls) == 1 and target.read_bytes() == before_file
            records[label] = {**observed, 'solves': observer.solves,
                'has_success_log': 'DEVSIM MEASUREMENT' in log,
                'history_delta': len(app.history) - history_len,
                'field_capture_attempts': 0 if label != 'normal' else None,
                'device_cleanup': not dv.get_device_list()}
        (out / 'bias.json').write_text(json.dumps({'pass': True, 'cases': records,
            'total_solves': sum(r['solves'] for r in records.values()), 'fault_injection_after_actual_success': True,
            'export_unchanged': True, 'file_sha256': hashlib.sha256(before_file).hexdigest()}, indent=2), encoding='utf-8')
        print('PASS requested bias matches; controlled post-success metadata mismatch blocks log/history/capture/export')
    finally:
        app.destroy()
        gui.filedialog.asksaveasfilename = old_dialog
        for name, callback in saved.items():
            setattr(gui.messagebox, name, callback)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
