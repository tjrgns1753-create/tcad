"""실제 Tk 입력 경계 검사. 물리 solve는 금지하고 호출 시도를 센다."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration')]
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
import tcad_2d_stagewise as G
from tcad.device.devsim import backend

def main():
    app=G.TCADApplication(); app.withdraw()
    calls=[]; errors=[]; cases={}
    def trap(*a,**kw):
        calls.append('engine_prepare')
        raise AssertionError('BACKEND_MUST_NOT_BE_PREPARED')
    app._notify_error=lambda *a: errors.append(str(a))
    try:
        with patch.object(backend,'is_available',trap), patch.object(backend,'require_devsim',trap):
            for text in ('nan','inf','-inf','bad'):
                app.last_doped_result=object()
                app.meas_voltage_var.set(text)
                before=len(errors)
                app.run_measurement()
                assert len(errors)==before+1 and not calls
                app.last_electrode_result=object()
                app.last_electrode_import=object()
                app.dc_drain_v_var.set(text)
                app._on_dc_operating_point_clicked()
                assert app.last_electrode_result is None and not calls
                cases[text]={'engine_prepare_attempts':len(calls),'previous_result_cleared':True}
            app.last_electrode_import=None
            app.last_electrode_result=object()
            assert app.run_dc_operating_point(.1,1.) is None
            assert app.last_electrode_result is None
            app._notify_info=lambda *a: None
            with patch('tkinter.filedialog.asksaveasfilename',trap):
                app._on_export_result_clicked()
            assert not calls
        # Controlled fault injection AFTER a real supported DD calculation.
        # This tests display rejection, not an observed engine failure.
        import test_uniform_resistor_dd_current_real as E
        from tcad.characterization import pn_junction_iv_sweep as sweep
        dv=backend.require_devsim()
        path=E.write_mesh(*E.mesh_arrays('one_sided',8),'e6nj_output')
        original=sweep.run_pn_junction_iv_sweep
        output_cases={}
        for label in ('nan_current','not_converged'):
            state,doped=E.canonical(path,'ACTIVE')
            app.wafer_state,app.last_doped_result,app.last_final_mesh=state,doped,path
            app.meas_axis_var.set('x'); app.meas_voltage_var.set(.001)
            def corrupt(*a,**kw):
                result=original(*a,**kw)
                if label=='nan_current':
                    result.points[0].currents[next(iter(result.points[0].currents))]=float('nan')
                else: result.points[0].converged=False
                return result
            before=len(errors); log0=app.log.get('1.0','end-1c')
            obs=E.Observer(dv); obs.install()
            try:
                with patch.object(sweep,'run_pn_junction_iv_sweep',corrupt): app.run_measurement()
            finally: obs.restore()
            log=app.log.get('1.0','end-1c')[len(log0):]
            assert len(errors)==before+1 and 'DEVSIM MEASUREMENT' not in log
            assert obs.solves>0 and not dv.get_device_list()
            output_cases[label]={'attempted_solves':obs.solves,'success_block_absent':True,'devices_remaining':0}
        out=ROOT/'e6nj_out'; out.mkdir(exist_ok=True)
        (out/'gui.json').write_text(json.dumps({'pass':True,'cases':cases,'failed_retry_no_export':True,
                                             'controlled_output_faults':output_cases},indent=2),encoding='utf-8')
        print(json.dumps(cases))
    finally:
        app.last_electrode_import=None
        app.destroy()

if __name__=='__main__': main()
