"""실제 Tk/공식 DEVSIM import 출처 차단; 새 물리 solve 없음."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration')]
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
import tcad_2d_stagewise as G
import test_uniform_resistor_dd_current_real as E
from tcad.device.devsim import backend
from tcad.characterization.source_context import capture_source_context,source_context_matches
from tcad.characterization.interface import CharacterizationResult,BiasPoint

def main():
    dv=backend.require_devsim()
    app=G.TCADApplication(); app.withdraw()
    errors=[]; app._notify_error=lambda *a:errors.append(str(a))
    records={}
    try:
        for case in ('state','pin','mesh_bytes','missing_context'):
            path=E.write_mesh(*E.mesh_arrays('one_sided',8),'e6nk_'+case)
            state,doped=E.canonical(path,'ACTIVE')
            app.wafer_state,app.last_doped_result,app.last_final_mesh=state,doped,path
            app.electrode_pins=[]
            app.add_electrode_pin('Source','Source',0.,-.25)
            app.add_electrode_pin('Drain','Drain',2.,-.25)
            imported=app.resolve_electrode_pins()
            assert imported is not None,errors
            assert source_context_matches(app._electrode_import_context,path,state,app.electrode_pins)
            if case=='state': app.wafer_state=E.canonical(path,'ACTIVE')[0]
            elif case=='pin': app.electrode_pins[0].x_um=.1
            elif case=='mesh_bytes':
                with Path(path).open('ab') as f:f.write(b'\n')
            else: app._electrode_import_context=None
            obs=E.Observer(dv); obs.install()
            def trap(*a,**k):
                obs.solves+=1
                raise AssertionError('STALE_DEVICE_SOLVE_FORBIDDEN')
            dv.solve=trap
            before=len(errors)
            try: assert app.run_dc_operating_point(.1,1.) is None
            finally:obs.restore()
            assert len(errors)==before+1 and obs.solves==0 and obs.writes==[]
            assert app.last_electrode_import is None and not dv.get_device_list()
            records[case]={'solves':obs.solves,'doping_writes':len(obs.writes),'devices_remaining':0}
        # Export wiring control is synthetic, not a physically calculated MOSFET.
        path=E.write_mesh(*E.mesh_arrays('one_sided',8),'e6nk_export')
        state,_=E.canonical(path,'ACTIVE')
        app.wafer_state,app.last_final_mesh=state,path
        app.last_electrode_result=CharacterizationResult('synthetic', 'not_a_device','Si','Drain',
                                                       [BiasPoint({'Source':0.,'Drain':.1},{'Source':-1.,'Drain':1.})])
        app._electrode_result_context=capture_source_context(path,state,app.electrode_pins)
        with tempfile.TemporaryDirectory() as tmp:
            csv=Path(tmp)/'control.csv'
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(csv)):
                app._on_export_result_clicked()
            assert csv.is_file() and len(csv.read_text().splitlines())==2
        app.wafer_state=E.canonical(path,'ACTIVE')[0]
        with patch('tkinter.filedialog.asksaveasfilename',side_effect=AssertionError('STALE_EXPORT_DIALOG')):
            app._on_export_result_clicked()
        assert app.last_electrode_result is None
        out=ROOT/'e6nk_out';out.mkdir(exist_ok=True)
        (out/'context.json').write_text(json.dumps({'pass':True,'cases':records,'same_source_export':True,
                                                  'stale_export_blocked':True,'export_control':'SYNTHETIC'},indent=2),encoding='utf-8')
        print(json.dumps(records))
    finally:
        app._cleanup_electrode_device()
        app.destroy()
if __name__=='__main__':main()
