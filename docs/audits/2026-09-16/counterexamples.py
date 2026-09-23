"""Diagnostic counterexamples; production code is called without modification.

Modes: state (pure production state), oxidation (real ViennaPS), gui (real
GUI + ViennaPS + DevSim; solve wrapper only records, always calls original).
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import run_audit  # audit-only DLL/thread environment

ROOT = run_audit.ROOT
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def state_checks():
    from tcad.physics import wafer_state_v2 as v
    from tcad.physics.wafer_state_accumulation import advance_wafer_state
    from tcad.mesh.interface import DopingProfile, DopingRegion
    from dataclasses import replace

    def init():
        return v.initialize_wafer_state(cells=[("Si", (-2, 2, -2, 0), "Si0")])
    def profile(c):
        return SimpleNamespace(doping=DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=c)]))
    def q(s,x=0,y=-1):
        a=s.net_doping_at(x,y)
        return dict(net=a.net_doping, status=a.physics_status)
    original=advance_wafer_state(init(),profile(1e17),"doping")
    masks={"edge_1um":[dict(min_um=-2,max_um=-1)],
           "center_1um":[dict(min_um=-0.5,max_um=0.5)]}
    result={"mask_translation":{}}
    for name,w in masks.items():
        s=advance_wafer_state(original,profile(5e18),"doping",barrier_windows=w)
        result["mask_translation"][name]=dict(attachments=len(s.attachments),
            under=q(s,(w[0]["min_um"]+w[0]["max_um"])/2),open=q(s,1.5))
    result["chemical_state"]={}
    for chemical in ("CHEMICAL","UNKNOWN","ACTIVE"):
        s=v.attach_dopant(init(),species="B",polarity="acceptor",concentration_at=lambda x,y:1e18,
                         inventory_integral=v.uniform_inventory_integral(1e18),support_instance_id="Si0",
                         support_region_um=(-2,2,-2,0),model="diagnostic",chemical_state=chemical)
        result["chemical_state"][chemical]=q(s)
    t=v.GeometryTransform(process_category="oxidation",representable=True,
        converted_extents_um=((-2,2,-0.3,0),),input_instance_ids=("Si0",))
    ox=v.advance(original,t,step_seed="oxidation_probe")
    oxide=[c for c in ox.active_cells() if c.material=="SiO2"]
    result["conversion_volume"]=dict(consumed_Si_area_um2=1.2,
        oxide_area_um2=sum(v.area_cm2(c.bounds_um)/1e-8 for c in oxide),
        oxide_bounds=[c.bounds_um for c in oxide],deep_query=q(ox))
    overlap=v.advance(original,v.GeometryTransform(process_category="deposition",representable=True,
        added_cells=(("Si",(-1,1,-1.5,0.5),"newSi"),),output_instance_ids=("newSi",)),step_seed="overlap")
    result["overlapping_deposition"]=dict(cells=[(c.material_instance_id,c.bounds_um) for c in overlap.active_cells()],
        original=q(original),after=q(overlap),events=[e.category for e in overlap.events])
    # A top-open trench yields multiple attachment rectangles meeting along
    # artificial subdivision edges; those edges must not double concentration.
    cut=v.advance(original,v.GeometryTransform(process_category="etching",representable=True,
        removed_extents_um=((-0.5,0.5,-1.5,0),),input_instance_ids=("Si0",)),step_seed="cut")
    result["split_boundary"]={str((x,y)):q(cut,x,y) for x,y in [(-1,-1.5),(-1,-1.500001),(-1,-1.499999)]}
    result["outside_geometry"]=q(original,2.01,-1)
    repeated=original
    for extent in ((-2,-1.5,-2,0),(1.5,2,-2,0)):
        repeated=v.advance(repeated,v.GeometryTransform(process_category="etching",representable=True,
            removed_extents_um=(extent,),input_instance_ids=("Si0",)),step_seed="etching")
    event_ids=[e.event_id for e in repeated.events]
    result["repeated_etch_provenance"]=dict(event_count=len(event_ids),unique_event_count=len(set(event_ids)),
        removal_events=[dict(id=e.event_id,extent=e.extent_um,inventory=e.inventory_cm_per_depth)
                        for e in repeated.events if e.category=="REMOVED"])
    return result


def oxidation_checks():
    import meshio
    import numpy as np
    import tcad.process.oxidation
    from tcad.process import registry
    from tcad.backends.viennaps import session
    vp=session.require_viennaps()
    result=[]
    for grid in (0.1,0.05,0.02):
        for hours in (0.0,0.01):
            with tempfile.TemporaryDirectory() as tmp:
                recipe=dict(grid_delta_um=grid,x_extent_um=2.,y_extent_um=2.,silicon_depth_um=1.,
                            mask_spans_um=[],pr_thickness_um=.2,oxidant="Dry",temperature_c=1000.,time_hours=hours)
                step=registry.get("oxidation","thermal")()
                r=step.run(recipe,tmp)
                m=meshio.read(r["final_mesh"])
                tops={}
                for c,tag in zip(m.cells,m.cell_data["Material"]):
                    for material in ("Si","SiO2"):
                        selected=c.data[np.asarray(tag).ravel()==int(getattr(vp.Material,material))]
                        if len(selected):
                            tops[material]=max(tops.get(material,-float("inf")),float(m.points[np.unique(selected),1].max()))
                row=dict(grid_um=grid,time_hr=hours,tops_um=tops,
                         oxide_thickness_um=tops.get("SiO2",tops["Si"])-tops["Si"],
                         Si_consumed_um=-tops["Si"])
                print("OXIDATION_PROBE",json.dumps(row),flush=True)
                result.append(row)
    return result


def gui_checks():
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend
    d=backend.require_devsim()
    app=gui.TCADApplication()
    app.withdraw()
    for name in ("showinfo","showerror","showwarning"):
        setattr(gui.messagebox,name,lambda *a,**k:None)
    app.wafer.width_um=4.
    app.wafer.silicon_depth_um=1.
    app.grid_var.set(.2)
    app.meas_voltage_var.set(.01)
    app.meas_axis_var.set("x")
    result={}
    original_solve=d.solve
    calls=[]
    def observe(*args,**kwargs):
        calls.append(kwargs.copy())
        return original_solve(*args,**kwargs)
    d.solve=observe
    try:
        assert app._materialize_current_wafer()
        app.doping_kind.set("Implant Windows")
        for n,value in {"dope_win_donor_bg_var":1e16,"dope_win_acceptor_bg_var":0,
                        "dope_win_src_donor_var":1e16,"dope_win_src_acceptor_var":0,
                        "dope_win_drn_donor_var":1e16,"dope_win_drn_acceptor_var":0}.items():
            getattr(app,n).set(value)
        assert app.run_doping(silent=True)
        app._on_thermal_anneal_clicked()
        a=app.wafer_state.net_doping_at(0,-.5)
        result["before_measurement"]=dict(net=a.net_doping,status=a.physics_status,attachments=len(app.wafer_state.attachments))
        app.run_measurement()
        log=app.log.get("1.0","end")
        result["solve_calls_after_unsupported_anneal"]=len(calls)
        result["gui_log"]=log
        result["after_measurement_net"]=app.wafer_state.net_doping_at(0,-.5).net_doping
        (OUT/"gui_measurement_full.log").write_text(log,encoding="utf-8")
    finally:
        d.solve=original_solve
        app.destroy()
    return result


def diode_checks():
    import importlib.util
    import math
    import numpy as np
    from tcad.device.devsim import backend
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.physics.wafer_state_accumulation import initial_wafer_state_from_recipe, advance_wafer_state
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    spec=importlib.util.spec_from_file_location("audit_fixture",ROOT/"tests/integration/test_wafer_state_v2_initial_geometry_devsim_real.py")
    fixture=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    d=backend.require_devsim()
    rows=[]
    for idx,grid in enumerate((.2,.1,.05)):
        with tempfile.TemporaryDirectory() as tmp:
            fixture.RECIPE["grid_delta_um"]=grid
            process=fixture._bare_rectangle_process_result(tmp)
            doping=1e16
            process=apply_step_junction_doping(process,region="Si",junction_axis="x",junction_position_um=0.,
                                              donor_conc_cm3=doping,acceptor_conc_cm3=doping)
            state=advance_wafer_state(initial_wafer_state_from_recipe(fixture.RECIPE),process,"doping")
            dev=import_process_result(process,mesh_name=f"audit_diode_mesh{idx}",device_name=f"audit_diode{idx}",
                contact_regions=["Si"],contact_axis="x",length_scale_to_cm=1e-4,
                refine_near_um=0.,refine_axis="x")
            try:
                apply_doping(dev.device,"Si",state,length_scale_to_cm=1e-4)
                def values(name):
                    return np.asarray(d.get_node_model_values(device=dev.device,region="Si",name=name))
                p_contact,n_contact=dev.contacts
                snapshots=[]
                original=d.solve
                def capture(*args,**kwargs):
                    answer=original(*args,**kwargs)
                    vt=d.get_parameter(device=dev.device,region="Si",name="V_t")
                    ni=d.get_parameter(device=dev.device,region="Si",name="n_i")
                    eps=d.get_parameter(device=dev.device,region="Si",name="Permittivity")
                    qe=d.get_parameter(device=dev.device,region="Si",name="ElectronCharge")
                    vn=d.get_parameter(device=dev.device,name=f"{n_contact}_bias")
                    x=values("x")
                    phi=values("Potential")
                    ns="Electrons" if "Electrons" in d.get_node_model_list(device=dev.device,region="Si") else "IntrinsicElectrons"
                    ps="Holes" if ns=="Electrons" else "IntrinsicHoles"
                    rho=values("NetDoping")+values(ps)-values(ns)
                    ux=np.unique(np.round(x,14))
                    meanrho=np.array([np.mean(np.abs(rho[np.isclose(x,k,rtol=0,atol=1e-14)])) for k in ux])
                    vb=vt*math.log(doping*doping/(ni*ni))
                    w=math.sqrt(4*eps*(vb+vn)/(qe*doping))*1e4
                    snapshots.append(dict(n_bias_V=vn,barrier_V=float(np.ptp(phi)),
                        analytic_barrier_V=vb+vn,W_depletion_um=w,
                        W_integrated_abs_charge_um=float(np.trapezoid(meanrho/doping,ux)*1e4)))
                    return answer
                d.solve=capture
                try:
                    sweep=run_pn_junction_iv_sweep(device=dev.device,region="Si",all_contacts=dev.contacts,
                        sweep_contact=n_contact,sweep_voltages=[-.2,0.,.2],fixed_contacts={p_contact:0.})
                finally:
                    d.solve=original
                points=[dict(n_bias_V=p.voltages[n_contact],currents_per_cm=p.currents,
                             KCL_relative=abs(sum(p.currents.values()))/max(max(abs(i) for i in p.currents.values()),1e-30)) for p in sweep.points]
                row=dict(grid_um=grid,nodes=len(values("x")),snapshots=snapshots,points=points,
                         interpretation="W_charge is integrated net space charge / doping, not an exact sharp depletion boundary")
                rows.append(row)
                print("DIODE_PROBE",json.dumps(row),flush=True)
            finally:
                d.delete_device(device=dev.device)
                d.delete_mesh(mesh=dev.mesh)
    return rows


if __name__ == "__main__":
    mode=sys.argv[1]
    result={"state":state_checks,"oxidation":oxidation_checks,"gui":gui_checks,"diode":diode_checks}[mode]()
    (OUT/f"counterexample_{mode}.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("COUNTEREXAMPLE_RESULT",json.dumps(result),flush=True)
