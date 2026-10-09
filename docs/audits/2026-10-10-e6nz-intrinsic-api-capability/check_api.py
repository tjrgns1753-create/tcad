"""실제 엔진 조사는 GitHub에 한정. 가짜 zero profile이나 모델 변경 없음."""
import hashlib
import json
import os
from pathlib import Path
import sys
if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
    raise RuntimeError('REMOTE_ONLY')
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PLAN_SHA='c44af795c4fcdca1343aac1ade194d9d0d7f8b060805ae929c2f81f22c9e7874'
if hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=PLAN_SHA:
    raise RuntimeError('PLAN_HASH_MISMATCH')
sys.path[:0]=[str(ROOT),str(ROOT/'tests/integration'),str(HERE)]
import test_uniform_resistor_dd_current_real as fixture
from tcad.device.devsim import backend
from tcad.device.devsim.mesh_import import import_process_result
from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe
from tcad.physics.wafer_state_v2 import advance
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
from devsim.python_packages.simple_physics import ece_name, hce_name
from judge import judge, BIASES

def main():
    out=ROOT/'e6nz_out'; out.mkdir(exist_ok=True)
    dv=backend.require_devsim()
    assert not dv.get_device_list() and not dv.get_mesh_list()
    points,triangles=fixture.mesh_arrays('one_sided',8)
    path=fixture.write_mesh(points,triangles,'known_undoped')
    process=build_process_result({'final_mesh':path,'snapshots':[]})
    state=initial_wafer_state_from_recipe({'x_extent_um':2.,'silicon_depth_um':.5,'grid_delta_um':.25})
    assert process.doping is None and not state.attachments
    initial_state=state
    canonical_before=[state.net_doping_at(float(p[0]),float(p[1])).net_doping for p in points]
    assert canonical_before and all(v==0. for v in canonical_before)
    data={'cases':{},'blocked':{},'plan_sha':PLAN_SHA,'provenance':'DIRECT_EXPLICIT_GEOMETRY_KNOWN_UNDOPED'}
    def save():
        (out/'records.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    for name,voltage in BIASES.items():
        obs=fixture.Observer(dv); obs.install(); imported=None
        try:
            imported=import_process_result(process,mesh_name=name+'_mesh',device_name=name+'_device',contact_regions=['Si'],contact_axis='x',length_scale_to_cm=1e-4)
            device=imported.device; contacts=list(imported.contacts)
            assert len(contacts)==2
            apply_doping(device,'Si',state,length_scale_to_cm=1e-4)
            result=run_pn_junction_iv_sweep(device=device,region='Si',all_contacts=contacts,sweep_contact=contacts[1],sweep_voltages=[voltage],fixed_contacts={contacts[0]:0.})
            arrays={key:list(dv.get_node_model_values(device=device,region='Si',name=key)) for key in ('x','y','Potential','Electrons','Holes','Donors','Acceptors','NetDoping')}
            params={key:dv.get_parameter(device=device,region='Si',name=key) for key in ('ElectronCharge','n_i','T','mu_n','mu_p','taun','taup')}
            currents={c:{'electron':dv.get_contact_current(device=device,contact=c,equation=ece_name),'hole':dv.get_contact_current(device=device,contact=c,equation=hce_name)} for c in contacts}
            canonical_after=[state.net_doping_at(float(p[0]),float(p[1])).net_doping for p in points]
            data['cases'][name]={'voltage':voltage,'solves':obs.solves,'attachments':len(state.attachments),'state_identity':state is initial_state,'canonical_before':canonical_before,'canonical_after':canonical_after,'contacts':contacts,'arrays':arrays,'params':params,'currents':currents,'result_current':dict(result.points[0].currents),'result_metadata':dict(result.metadata)}
        finally:
            obs.restore()
            if imported is not None:
                dv.delete_device(device=imported.device); dv.delete_mesh(mesh=imported.mesh)
        data['cases'][name].update(devices_after=list(dv.get_device_list()),meshes_after=list(dv.get_mesh_list())); save()
    for name,prior in (('missing',None),('unresolved',advance(state,None,step_seed='etching'))):
        obs=fixture.Observer(dv); obs.install(); imported=None
        try:
            imported=import_process_result(process,mesh_name=name+'_mesh',device_name=name+'_device',contact_regions=['Si'],contact_axis='x',length_scale_to_cm=1e-4)
            try:
                apply_doping(imported.device,'Si',prior,length_scale_to_cm=1e-4)
            except UnsupportedDopingState as exc:
                data['blocked'][name]={'refused':True,'resolution':exc.physics_status['resolution'],'solves':obs.solves,'writes':len(obs.writes)}
            else:
                data['blocked'][name]={'refused':False,'solves':obs.solves,'writes':len(obs.writes)}
        finally:
            obs.restore()
            if imported is not None:
                dv.delete_device(device=imported.device); dv.delete_mesh(mesh=imported.mesh)
        data['blocked'][name].update(devices_after=list(dv.get_device_list()),meshes_after=list(dv.get_mesh_list())); save()
    verdict=judge(data)
    (out/'verdict.json').write_text(json.dumps(verdict,indent=2),encoding='utf-8')
    print(json.dumps({'pass':verdict['pass'],'checks':len(verdict['checks']),'solves':sum(r['solves'] for r in data['cases'].values())}))
    return 0 if verdict['pass'] else 1

if __name__=='__main__':
    raise SystemExit(main())
