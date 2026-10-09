"""기존 선언 API·canonical accumulation·GUI·공식 API로 12개 실제 요청."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/integration'))
PLAN_SHA = 'd02b200d650bd0cb5e5aaa20de298b6bd94bcf2e5a390cff499241190384a7ef'


def main():
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    plan = Path(__file__).with_name('PLAN_BOUNDARY.md').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(plan).hexdigest() != PLAN_SHA:
        raise ValueError('PLAN_HASH_MISMATCH_BEFORE_ENGINE_IMPORT')
    from judge import PROFILES, CASES
    from judge_boundary import evaluate
    import test_uniform_resistor_dd_current_real as base
    from tcad.device.devsim import backend
    from tcad.characterization import node_fields
    from tcad.characterization.source_context import source_evidence
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_uniform_doping
    from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
    import tcad_2d_stagewise as gui
    dv = backend.require_devsim()
    points, triangles = base.mesh_arrays('one_sided', 8)
    path = base.write_mesh(points, triangles, 'carrier_order_boundary')
    out = ROOT / 'e6nu_boundary_out'
    out.mkdir(exist_ok=True)
    live, records = {}, {}
    original_capture = node_fields.capture_node_fields

    def query_at(state, x, y):
        q = state.net_doping_at(float(x), float(y))
        return {'donor':q.donor_concentration,'acceptor':q.acceptor_concentration,
                'net':q.net_doping,'physics_status':q.physics_status}

    def capture(module, device, region, scale):
        live['capture_attempts'] += 1
        fields = original_capture(module, device, region, scale)
        for key, model in node_fields.FIELD_NAMES.items():
            assert tuple(module.get_node_model_values(device=device, region=region, name=model)) == getattr(fields, key)
        live['params'] = {key: float(module.get_parameter(device=device, region=region, name=key))
            for key in ('ElectronCharge', 'n_i', 'T', 'V_t', 'mu_n', 'mu_p', 'taun', 'taup')}
        live['doping_arrays'] = {model: list(module.get_node_model_values(device=device, region=region, name=model))
                                for model in ('Donors', 'Acceptors', 'NetDoping')}
        return fields

    node_fields.capture_node_fields = capture
    saved = {name: getattr(gui.messagebox, name) for name in base.MESSAGEBOX if hasattr(gui.messagebox, name)}
    for name in saved:
        setattr(gui.messagebox, name, lambda *a, **kw: None)
    app = gui.TCADApplication()
    app.withdraw()
    errors = []
    app._notify_error = lambda *args: errors.append(str(args))
    original_dialog = gui.filedialog.asksaveasfilename
    try:
        for name, profile, voltage in CASES:
            live.clear()
            live['capture_attempts'] = 0
            state = initial_wafer_state_from_recipe({'x_extent_um':2.,'silicon_depth_um':.5,'grid_delta_um':.25})
            pr = build_process_result({'final_mesh':path,'snapshots':[]})
            for donor,acceptor in PROFILES[profile]:
                doped = apply_uniform_doping(pr, donor_by_region_cm3={'Si':donor},
                    acceptor_by_region_cm3={'Si':acceptor}, chemical_state='ACTIVE')
                state = advance_wafer_state(state, doped, 'doping')
            query = state.net_doping_at(0., -.25)
            canonical_query = {'donor':query.donor_concentration,'acceptor':query.acceptor_concentration,
                               'net':query.net_doping,'physics_status':query.physics_status}
            app.last_final_mesh, app.last_doped_result, app.wafer_state = path,doped,state
            app.meas_axis_var.set('x')
            app.meas_source_pin.set('max')
            app.meas_voltage_var.set(voltage)
            start_errors = len(errors)
            history_before = len(app.history)
            queries_before = [query_at(state, point[0], point[1]) for point in points]
            log_before = app.log.get('1.0','end-1c')
            observer = base.Observer(dv)
            observer.install()
            try:
                app.run_measurement()
            finally:
                observer.restore()
            if profile not in {'n_single','p_single'}:
                assert len(errors) == start_errors + 1 and 'COMPENSATED_TRANSPORT_MODEL_MISSING' in errors[-1]
                fields, result = app._measurement_fields, app._measurement_fields_result
                field_nodes = {}
                for layer in node_fields.FIELD_NAMES:
                    app.viewer_layer_var.set(layer)
                    app.redraw()
                    field_nodes[layer] = len(app.canvas.find_withtag('solved_field_node'))
                target = out / (name + '_blocked.json')
                dialog_calls = []
                def blocked_dialog(**kw):
                    dialog_calls.append(True)
                    return str(target)
                gui.filedialog.asksaveasfilename = blocked_dialog
                app._on_export_node_fields_clicked()
                status = app.last_physics_status
                records[name] = {'profile':profile,'voltage':voltage,'steps':PROFILES[profile],
                    'canonical_query':canonical_query,'canonical_queries_before':queries_before,
                    'canonical_queries_after':[query_at(app.wafer_state, point[0], point[1]) for point in points],
                    'attachment_count':len(app.wafer_state.attachments),'state_identity_preserved':app.wafer_state is state,
                    'outcome':status['resolution'],'reason_code':status['reason_code'],
                    'solves':observer.solves,'doping_writes':len(observer.writes),
                    'field_capture_attempts':live['capture_attempts'],
                    'snapshot':asdict(fields) if fields is not None else None,
                    'measurement':asdict(result) if result is not None else None,
                    'success_log_present':'DEVSIM MEASUREMENT' in app.log.get('1.0','end-1c')[len(log_before):],
                    'history_delta':len(app.history)-history_before,'field_nodes':field_nodes,
                    'export_dialog_calls':len(dialog_calls),'export_created':target.exists(),
                    'device_cleanup':not dv.get_device_list()}
                (out/'records.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
                print(name, 'TRANSPORT_BLOCKED', status['reason_code'], 'solves',observer.solves,'writes',len(observer.writes),flush=True)
                continue
            assert len(errors) == start_errors, (name,errors[start_errors:])
            fields,result = app._measurement_fields,app._measurement_fields_result
            assert fields is not None and result is not None and observer.solves == 3
            assert not dv.get_device_list()
            rendered = {}
            for layer in node_fields.FIELD_NAMES:
                app.viewer_layer_var.set(layer)
                app.redraw()
                notes = app.canvas.find_withtag('solved_field_note')
                assert len(notes) == 1
                rendered[layer] = {'nodes':len(app.canvas.find_withtag('solved_field_node')),
                                   'text':app.canvas.itemcget(notes[0],'text')}
            target = out / (name+'_fields.json')
            gui.filedialog.asksaveasfilename = lambda **kw: str(target)
            app._on_export_node_fields_clicked()
            assert target.is_file() and len(errors) == start_errors
            exported = json.loads(target.read_text(encoding='utf-8'))
            point = result.points[0]
            assert exported['snapshot'] == json.loads(json.dumps(asdict(fields)))
            assert exported['measurement']['voltages'] == point.voltages
            assert exported['measurement']['currents'] == point.currents
            records[name] = {'profile':profile,'voltage':voltage,'steps':PROFILES[profile],
                'canonical_query':canonical_query,'attachment_count':len(state.attachments),
                'params':live['params'],'doping_arrays':live['doping_arrays'],
                'snapshot':asdict(fields),'measurement':asdict(result),'rendered':rendered,
                'solves':observer.solves,'device_cleanup':not dv.get_device_list(),'live_api_equal':True,
                'export_equal':True,'success_log_present':'DEVSIM MEASUREMENT' in app.log.get('1.0','end-1c')[len(log_before):],
                'source_evidence':source_evidence(app._measurement_fields_context),
                'file_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            (out/'records.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
            print(name,canonical_query,point.currents,flush=True)
        # JSON-roundtrip restores the same sequence representation the artifact judge reads.
        verdict = evaluate(json.loads(json.dumps(records)))
        (out/'verdict.json').write_text(json.dumps(verdict,indent=2),encoding='utf-8')
        print(json.dumps({'pass':verdict['pass'],'cases':len(records),'solves':sum(r['solves'] for r in records.values())}))
        return 0 if verdict['pass'] else 1
    finally:
        app.destroy()
        node_fields.capture_node_fields = original_capture
        gui.filedialog.asksaveasfilename = original_dialog
        for name,callback in saved.items():
            setattr(gui.messagebox,name,callback)


if __name__ == '__main__':
    raise SystemExit(main())
