"""실제 GUI/API/JSON 일치와 물성 기록 결손 차단. 원격만 실행."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_measurement_canonical_state_gate_real import _measure, _configure, _assert_supported
from tcad.characterization.transport_evidence import PARAMETER_UNITS, transport_model_note
from tcad.characterization.io import save_json, save_measurement_bundle


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    import devsim.python_packages.simple_physics  # official aliases before observer
    app = gui.TCADApplication()
    modal = []
    names = ('showinfo', 'showerror', 'showwarning', 'askquestion', 'askyesno',
             'askyesnocancel', 'askokcancel', 'askretrycancel')
    originals = {n: getattr(gui.messagebox, n) for n in names}
    for n in names:
        setattr(gui.messagebox, n, lambda *a, _name=n, **kw: modal.append(_name) or True)
    metrics = {}
    try:
        app.withdraw()
        app.update_idletasks()
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
            live = []
            get = dv.get_parameter

            def observe(**kw):
                value = get(**kw)
                if kw.get('name') in PARAMETER_UNITS:
                    assert kw['device'] in dv.get_device_list()
                    live.append((dict(kw), value))
                return value

            notifications = []
            with patch.object(dv, 'get_parameter', observe), patch.object(app, '_notify_info',
                    side_effect=lambda title, msg: notifications.append(msg)):
                b = _measure(app, dv, label)
            if label != 'intrinsic':
                _assert_supported(label, b)
            else:
                assert b['solve_calls'] == 3 and b['measurement_section_logged'], b
            result = app._measurement_fields_result
            assert result is not None
            record = result.metadata['transport_model']
            assert record['material_calibration'] == 'NOT_VALIDATED'
            for key, entry in record['parameters'].items():
                assert any(kw['name'] == key and kw['device'] == result.device and
                           kw['region'] == result.region and value == entry['value']
                           for kw, value in live), (key, live)
                assert entry['unit'] == PARAMETER_UNITS[key]
            note = transport_model_note(result.metadata)
            assert note in b['log_delta'] and len(notifications) == 1 and note in notifications[0]
            assert record['parameters']['taun']['value'] == record['parameters']['taup']['value'] == 1e-8
            assert record['parameters']['mu_n']['value'] == 400. and record['parameters']['mu_p']['value'] == 200.
            assert record['parameters']['n_i']['value'] == 1e10 and record['parameters']['T']['value'] == 300.
            if label != 'intrinsic':
                expected = .0016 if label == 'n' else .0004
                assert abs(b['currents_in_log'][0] / expected - 1) <= 1e-6, b
            else:
                assert 'intrinsic_analytic_validation' in result.metadata
            with tempfile.TemporaryDirectory() as tmp:
                direct = Path(tmp) / 'measurement.json'
                csv = Path(tmp) / 'measurement.csv'
                save_json(result, direct)
                companion = save_measurement_bundle(result, csv)
                for path in (direct, Path(companion)):
                    assert json.loads(path.read_text(encoding='utf-8'))['metadata']['transport_model'] == record
            metrics[label] = {'solve_calls': b['solve_calls'], 'currents': b['currents_in_log'],
                              'transport_model': record, 'same_gui_and_export': True}
            assert not dv.get_device_list()

        # Keep a successful prior result in the session: faults must clear it.
        for key, fault in (('n_i', 'missing'), ('mu_n', 'nan')):
            app.reset()
            _configure(app)
            assert app._materialize_current_wafer()
            app.doping_kind.set('Uniform')
            app.dope_uniform_donor_var.set(1e16)
            app.dope_uniform_acceptor_var.set(0.)
            assert app.run_doping()
            good = _measure(app, dv, 'prior')
            _assert_supported('prior', good)
            assert app._measurement_fields_result is not None
            get = dv.get_parameter

            def inject(**kw):
                if kw.get('name') == key:
                    if fault == 'missing':
                        raise RuntimeError('injected missing parameter')
                    return float('nan')
                return get(**kw)

            with patch.object(dv, 'get_parameter', inject):
                b = _measure(app, dv, fault)
            assert b['solve_calls'] == 1, b  # actual Poisson only; DD never called
            assert not b['currents_in_log'] and not b['measurement_section_logged']
            assert b['history_entries_added'] == 0
            assert b['last_physics_status']['reason_code'] == 'TRANSPORT_PARAMETER_EVIDENCE_INVALID'
            assert app._measurement_fields is None and app._measurement_fields_result is None
            assert not dv.get_device_list()
            metrics[fault] = {'solve_calls': b['solve_calls'], 'reported_currents': 0, 'fields_cleared': True}
        assert not modal, modal
        print('TRANSPORT_METRICS ' + json.dumps(metrics, allow_nan=False))
        print('PASS: real n/p/intrinsic API→GUI→export; two faults block DD and clear stale evidence')
    finally:
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
        app.destroy()


if __name__ == '__main__':
    main()
