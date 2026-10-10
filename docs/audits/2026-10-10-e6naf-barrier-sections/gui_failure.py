"""Actual withdrawn Tk; detector exception must not attach or solve."""
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests/integration"))


def main():
    assert os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted", "REMOTE_ONLY"
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend, mesh_import
    from test_gui_doping_donor_acceptor_real import _configure,MESSAGEBOX
    dv=backend.require_devsim(); app=gui.TCADApplication(); modal=[]
    saved={n:getattr(gui.messagebox,n) for n in MESSAGEBOX}
    for n in saved: setattr(gui.messagebox,n,lambda *a,_n=n,**k:modal.append(_n))
    try:
        app.withdraw(); app.update_idletasks(); _configure(app)
        assert app._materialize_current_wafer()
        app.doping_kind.set("Uniform");app.dope_uniform_region_var.set("Si")
        app.dope_uniform_donor_var.set(1e16);app.dope_uniform_acceptor_var.set(0)
        prior=app.wafer_state; cached=app.last_doped_result; history=len(app.history)
        def forbidden(*a,**kw): raise AssertionError("ATTACH_OR_SOLVE_AFTER_UNKNOWN_BARRIER")
        with patch.object(mesh_import,"derive_barrier_covered_windows",side_effect=ValueError("synthetic malformed geometry")), \
             patch.object(gui,"advance_wafer_state",side_effect=forbidden) as attach, \
             patch.object(dv,"solve",side_effect=forbidden) as solve, \
             patch.object(dv,"set_node_values",side_effect=forbidden) as writes:
            assert app.run_doping() is False
            assert attach.call_count==solve.call_count==writes.call_count==0
        assert app.wafer_state is prior and app.last_doped_result is cached and len(app.history)==history
        assert app.last_physics_status["reason_code"]=="BARRIER_GEOMETRY_UNRESOLVED"
        assert "DOPING NOT APPLIED" in app.log.get("1.0","end-1c") and modal==[]
        assert not dv.get_device_list()
        print("PASS actual GUI detector failure; attach/write/solve/modal 0; prior state identical")
    finally:
        for n,f in saved.items():setattr(gui.messagebox,n,f)
        app.destroy()


if __name__=="__main__": main()
