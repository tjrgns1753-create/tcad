"""잘못된 canonical 농도가 실제 측정에서 쓰기/solve 전에 차단되는지 검사."""
import json
import os
from dataclasses import replace
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration')]
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
import test_uniform_resistor_dd_current_real as E
import tcad_2d_stagewise as G
from tcad.device.devsim import backend

def main():
    dv=backend.require_devsim()
    path=E.write_mesh(*E.mesh_arrays('one_sided',8),'e6ni_invalid')
    app=G.TCADApplication(); app.withdraw()
    records={}
    try:
        for name,value in [('nan',float('nan')),('inf',float('inf')),('negative',-1.)]:
            s,doped=E.canonical(path,'ACTIVE')
            bad=replace(s.attachments[0],concentration_at=lambda x,y,value=value:value)
            s=replace(s,attachments=(bad,)+s.attachments[1:])
            app.wafer_state,app.last_doped_result,app.last_final_mesh=s,doped,path
            app.meas_axis_var.set('x'); app.meas_voltage_var.set(.001)
            obs=E.Observer(dv); obs.install()
            def trap(*args,**kwargs):
                obs.solves+=1
                raise AssertionError('SOLVE_MUST_NOT_BE_CALLED')
            dv.solve=trap
            try: app.run_measurement()
            finally: obs.restore()
            status=app.last_physics_status
            assert obs.solves==0 and obs.writes==[]
            assert status['resolution']=='UNSUPPORTED_BY_MODEL'
            assert any(e.get('parameter')=='dopant_concentration_validity' for e in status['entries'])
            assert not dv.get_device_list()
            records[name]={'attempted_solves':obs.solves,'doping_writes':len(obs.writes),
                           'resolution':status['resolution'],'parameter':'dopant_concentration_validity'}
        out=ROOT/'e6ni_out'; out.mkdir(exist_ok=True)
        (out/'invalid.json').write_text(json.dumps({'pass':True,'cases':records},indent=2),encoding='utf-8')
        print(json.dumps(records))
    finally: app.destroy()

if __name__=='__main__': main()
